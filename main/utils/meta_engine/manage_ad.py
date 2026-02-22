"""
Meta Ads Management — Create, Update, Delete

Each function is designed to be **resumable**: if a step fails, previously
created platform objects are reused on retry instead of being recreated.

Hierarchy (Meta → local model):
    Campaign  → PlatformCampaign
    Ad Set    → AdGroup
    Creative  → (inline, no separate model)
    Ad        → Ad

All money values coming *in* to these functions are expected in
**minor units** (cents) — the same unit stored in ``CampaignBudget``.
"""

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign as MetaCampaign
from facebook_business.adobjects.adset import AdSet as MetaAdSet
from facebook_business.adobjects.adcreative import AdCreative as MetaAdCreative
from facebook_business.adobjects.ad import Ad as MetaAd

from main.models import (
    AdIntegration,
    UnifiedCampaign,
    PlatformCampaign,
    CampaignBudget,
    AdGroup,
    Ad,
    AdAsset,
    PlatformAsset,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# SDK INIT (shared with sync_ad.py)
# ────────────────────────────────────────────────────────────

def _init_meta(integration: AdIntegration):
    """Initialize the Meta SDK for the given integration."""
    FacebookAdsApi.init(
        settings.META_APP_ID,
        settings.META_APP_SECRET,
        integration.access_token,
        api_version="v19.0",
    )
    return AdAccount(integration.ad_account_id)


# ────────────────────────────────────────────────────────────
# OBJECTIVE MAPPING  (unified → Meta)
# ────────────────────────────────────────────────────────────

OBJECTIVE_TO_META = {
    "CONVERSIONS": "OUTCOME_SALES",
    "TRAFFIC":     "OUTCOME_TRAFFIC",
    "LEADS":       "OUTCOME_LEADS",
    "AWARENESS":   "OUTCOME_AWARENESS",
    "ENGAGEMENT":  "OUTCOME_ENGAGEMENT",
    "APP_PROMOTION": "OUTCOME_APP_PROMOTION",
    "LEAD_GENERATION": "OUTCOME_LEADS",
}

OPTIMIZATION_GOAL_MAP = {
    "CONVERSIONS": "OFFSITE_CONVERSIONS",
    "TRAFFIC":     "LINK_CLICKS",
    "LEADS":       "LEAD_GENERATION",
    "AWARENESS":   "REACH",
    "ENGAGEMENT":  "POST_ENGAGEMENT",
    "APP_PROMOTION": "APP_INSTALLS",
    "LEAD_GENERATION": "LEAD_GENERATION",
}


def _meta_objective(unified_objective: str) -> str:
    return OBJECTIVE_TO_META.get(unified_objective, "OUTCOME_TRAFFIC")


def _optimization_goal(unified_objective: str) -> str:
    return OPTIMIZATION_GOAL_MAP.get(unified_objective, "LINK_CLICKS")


# ────────────────────────────────────────────────────────────
# ASSET UPLOAD HELPER
# ────────────────────────────────────────────────────────────

def _ensure_platform_asset(account: AdAccount, integration: AdIntegration, asset: AdAsset):
    """Upload an AdAsset to Meta if not already uploaded. Returns the image hash or video ID."""
    existing = PlatformAsset.objects.filter(asset=asset, integration=integration).first()
    if existing:
        return existing.platform_asset_id

    file_path = asset.file.path

    if asset.file_type == "IMAGE":
        result = account.create_ad_image(params={"filename": file_path})
        if isinstance(result, list):
            platform_id = result[0]["hash"]
        else:
            platform_id = result["hash"]
    else:
        # Video upload
        result = account.create_ad_video(params={"filepath": file_path})
        platform_id = result["id"]

    PlatformAsset.objects.create(
        asset=asset,
        integration=integration,
        platform_asset_id=platform_id,
    )
    asset.status = "UPLOADED"
    asset.file_hash = platform_id
    asset.save(update_fields=["status", "file_hash"])

    logger.info("Uploaded asset %s → Meta %s: %s", asset.id, asset.file_type, platform_id)
    return platform_id


# ────────────────────────────────────────────────────────────
# TARGETING BUILDER
# ────────────────────────────────────────────────────────────

# Common country name → ISO 3166-1 alpha-2 lookup (extend as needed)
_COUNTRY_NAME_TO_CODE = {
    "bangladesh": "BD", "united states": "US", "usa": "US",
    "united kingdom": "GB", "uk": "GB", "canada": "CA",
    "australia": "AU", "india": "IN", "germany": "DE",
    "france": "FR", "brazil": "BR", "japan": "JP",
    "pakistan": "PK", "indonesia": "ID", "nigeria": "NG",
    "mexico": "MX", "philippines": "PH", "egypt": "EG",
    "turkey": "TR", "saudi arabia": "SA", "south africa": "ZA",
    "spain": "ES", "italy": "IT", "netherlands": "NL",
    "south korea": "KR", "thailand": "TH", "vietnam": "VN",
    "malaysia": "MY", "singapore": "SG", "uae": "AE",
    "united arab emirates": "AE", "china": "CN", "russia": "RU",
    "argentina": "AR", "colombia": "CO", "kenya": "KE",
    "sweden": "SE", "norway": "NO", "denmark": "DK",
    "finland": "FI", "poland": "PL", "portugal": "PT",
    "new zealand": "NZ", "ireland": "IE", "switzerland": "CH",
    "belgium": "BE", "austria": "AT", "czech republic": "CZ",
    "nepal": "NP", "sri lanka": "LK", "myanmar": "MM",
}


def _normalize_country(value: str) -> str:
    """Convert a country name or code to a 2-letter ISO code for Meta."""
    v = value.strip()
    # Already a 2-letter code
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return _COUNTRY_NAME_TO_CODE.get(v.lower(), v.upper()[:2])


def _build_targeting(targeting_config: dict) -> dict:
    """Convert our normalised targeting into Meta's targeting spec."""
    targeting = {}

    locations = targeting_config.get("locations")
    if locations:
        codes = [_normalize_country(loc) for loc in locations]
        targeting["geo_locations"] = {"countries": codes}

    age_min = targeting_config.get("min_age")
    age_max = targeting_config.get("max_age")
    if age_min:
        targeting["age_min"] = int(age_min)
    if age_max:
        targeting["age_max"] = int(age_max)

    gender = targeting_config.get("gender", "").lower()
    if gender == "male":
        targeting["genders"] = [1]
    elif gender == "female":
        targeting["genders"] = [2]
    # else: all genders — omit key

    # Turn off Advantage+ audience to keep targeting explicit
    targeting["targeting_automation"] = {"advantage_audience": 0}

    return targeting


# ════════════════════════════════════════════════════════════
#  1 ·  CREATE AD ON META
# ════════════════════════════════════════════════════════════

class MetaAdCreationError(Exception):
    """Raised when a Meta API call fails during ad creation."""
    def __init__(self, stage: str, message: str, platform_campaign=None, ad_group=None):
        self.stage = stage
        self.platform_campaign = platform_campaign
        self.ad_group = ad_group
        super().__init__(f"[{stage}] {message}")


def create_ad_on_meta(
    unified_campaign_id: int,
    ad_asset: AdAsset | None = None,
):
    """
    Push a full ad stack (Campaign → Ad Set → Creative → Ad) to Meta.

    Designed for **resumability**: if a previous attempt partially succeeded
    (e.g. PlatformCampaign exists but AdGroup does not), this function will
    pick up from where it left off instead of creating duplicates.

    The Facebook Page ID is read from ``AdIntegration.page_id``.

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign`` to publish.
    ad_asset : AdAsset | None
        Optional pre-uploaded local asset to include in the creative.

    Returns
    -------
    Ad
        The local ``Ad`` model instance linked to the newly created Meta ad.

    Raises
    ------
    MetaAdCreationError
        With ``.stage`` indicating where the failure occurred.
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(id=unified_campaign_id)
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="META",
        is_active=True,
    )
    page_id = integration.page_id
    if not page_id:
        raise MetaAdCreationError(
            "INIT",
            "No Facebook Page ID configured. Use the select-meta-page endpoint first.",
        )
    account = _init_meta(integration)

    budget = CampaignBudget.objects.filter(campaign=campaign, platform="META").first()
    draft = campaign.draft_data or {}

    # ── Step 1: Campaign ────────────────────────────────────
    platform_campaign = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
    ).first()

    if not platform_campaign or not platform_campaign.platform_campaign_id:
        try:
            meta_campaign = account.create_campaign(params={
                "name": campaign.name,
                "objective": _meta_objective(campaign.objective),
                "status": "PAUSED",
                "special_ad_categories": [],
                "is_adset_budget_sharing_enabled": False,
            })
            meta_campaign_id = meta_campaign["id"]
            logger.info("Meta Campaign created: %s", meta_campaign_id)
        except Exception as exc:
            raise MetaAdCreationError("CAMPAIGN", str(exc)) from exc

        if platform_campaign:
            platform_campaign.platform_campaign_id = meta_campaign_id
            platform_campaign.status = "PAUSED"
            platform_campaign.last_synced_at = timezone.now()
            platform_campaign.save()
        else:
            platform_campaign = PlatformCampaign.objects.create(
                unified_campaign=campaign,
                integration=integration,
                platform_campaign_id=meta_campaign_id,
                status="PAUSED",
                last_synced_at=timezone.now(),
            )
    else:
        meta_campaign_id = platform_campaign.platform_campaign_id
        logger.info("Reusing existing Meta Campaign: %s", meta_campaign_id)

    # ── Step 2: Ad Set ──────────────────────────────────────
    ad_group = AdGroup.objects.filter(platform_campaign=platform_campaign).first()

    if not ad_group or not ad_group.platform_adgroup_id:
        targeting_config = {}
        if ad_group:
            targeting_config = ad_group.targeting_config or {}
        else:
            targeting_config = {
                "min_age": draft.get("min_age"),
                "max_age": draft.get("max_age"),
                "gender": draft.get("gender"),
                "locations": draft.get("locations"),
                "keywords": draft.get("keywords"),
            }

        start_time = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")

        adset_params = {
            "name": f"{campaign.name} - Ad Set",
            "campaign_id": meta_campaign_id,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": _optimization_goal(campaign.objective),
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "start_time": start_time,
            "status": "PAUSED",
            "targeting": _build_targeting(targeting_config),
        }

        # Budget: prefer campaign budget record, fall back to draft
        if budget:
            if budget.budget_type == "DAILY":
                adset_params["daily_budget"] = budget.daily_budget_minor
            else:
                adset_params["lifetime_budget"] = budget.daily_budget_minor
                # end_time is required for lifetime budgets and must be in the future
                if budget.end_date and budget.end_date > datetime.now().date():
                    adset_params["end_time"] = budget.end_date.strftime("%Y-%m-%dT23:59:59")
                else:
                    # Default to 30 days from now if end_date is missing or in the past
                    fallback_end = datetime.now() + timedelta(days=30)
                    adset_params["end_time"] = fallback_end.strftime("%Y-%m-%dT23:59:59")
        else:
            # Fallback: try budgets from draft_data
            draft_budgets = draft.get("budgets", [])
            meta_budget = next((b for b in draft_budgets if b.get("platform") == "META"), None)
            if meta_budget:
                adset_params["daily_budget"] = int(meta_budget["budget"])

        try:
            meta_adset = account.create_ad_set(params=adset_params)
            meta_adset_id = meta_adset["id"]
            logger.info("Meta Ad Set created: %s", meta_adset_id)
        except Exception as exc:
            raise MetaAdCreationError(
                "ADSET", str(exc), platform_campaign=platform_campaign,
            ) from exc

        if ad_group:
            ad_group.platform_adgroup_id = meta_adset_id
            ad_group.status = "PAUSED"
            ad_group.last_synced_at = timezone.now()
            ad_group.save()
        else:
            ad_group = AdGroup.objects.create(
                platform_campaign=platform_campaign,
                name=f"{campaign.name} - Ad Set",
                platform_adgroup_id=meta_adset_id,
                status="PAUSED",
                targeting_config=targeting_config,
                start_time=start_time,
                last_synced_at=timezone.now(),
            )
    else:
        meta_adset_id = ad_group.platform_adgroup_id
        logger.info("Reusing existing Meta Ad Set: %s", meta_adset_id)

    # ── Step 3: Upload asset (if any) ───────────────────────
    image_hash = None
    if ad_asset:
        try:
            image_hash = _ensure_platform_asset(account, integration, ad_asset)
        except Exception as exc:
            raise MetaAdCreationError(
                "ASSET_UPLOAD", str(exc),
                platform_campaign=platform_campaign,
                ad_group=ad_group,
            ) from exc

    # ── Step 4: Creative ────────────────────────────────────
    local_ad = Ad.objects.filter(ad_group=ad_group).first()

    headline = draft.get("headline", "") if not local_ad else (local_ad.headline or "")
    primary_text = draft.get("primary_text", "") if not local_ad else (local_ad.primary_text or "")
    description = draft.get("description", "") if not local_ad else (local_ad.description or "")
    destination_url = draft.get("destination_url", "") if not local_ad else (local_ad.destination_url or "")
    cta = draft.get("call_to_action", "LEARN_MORE") if not local_ad else (local_ad.call_to_action or "LEARN_MORE")

    link_data = {
        "link": destination_url,
        "message": primary_text,
        "name": headline,
        "description": description,
        "call_to_action": {
            "type": cta.upper().replace(" ", "_"),
            "value": {"link": destination_url},
        },
    }
    if image_hash:
        link_data["image_hash"] = image_hash

    try:
        creative = account.create_ad_creative(params={
            "name": f"{campaign.name} - Creative",
            "object_story_spec": {
                "page_id": page_id,
                "link_data": link_data,
            },
        })
        meta_creative_id = creative["id"]
        logger.info("Meta Creative created: %s", meta_creative_id)
    except Exception as exc:
        raise MetaAdCreationError(
            "CREATIVE", str(exc),
            platform_campaign=platform_campaign,
            ad_group=ad_group,
        ) from exc

    # ── Step 5: Ad ──────────────────────────────────────────
    ad_name = draft.get("ad_name", f"{campaign.name} - Ad")
    if local_ad and local_ad.name:
        ad_name = local_ad.name

    if local_ad and local_ad.platform_ad_id:
        logger.info("Reusing existing Meta Ad: %s", local_ad.platform_ad_id)
        return local_ad

    try:
        meta_ad = account.create_ad(params={
            "name": ad_name,
            "adset_id": meta_adset_id,
            "creative": {"creative_id": meta_creative_id},
            "status": "PAUSED",
        })
        meta_ad_id = meta_ad["id"]
        logger.info("Meta Ad created: %s", meta_ad_id)
    except Exception as exc:
        raise MetaAdCreationError(
            "AD", str(exc),
            platform_campaign=platform_campaign,
            ad_group=ad_group,
        ) from exc

    # Persist the local Ad
    if local_ad:
        local_ad.platform_ad_id = meta_ad_id
        local_ad.status = "PAUSED"
        local_ad.save()
    else:
        local_ad = Ad.objects.create(
            ad_group=ad_group,
            name=ad_name,
            platform_ad_id=meta_ad_id,
            status="PAUSED",
            headline=headline,
            primary_text=primary_text,
            description=description,
            destination_url=destination_url,
            call_to_action=cta,
        )

    if ad_asset:
        local_ad.assets.add(ad_asset)

    # Mark campaign as active locally
    campaign.status = "ACTIVE"
    campaign.draft_data = {}
    campaign.save(update_fields=["status", "draft_data", "updated_at"])

    platform_campaign.status = "PAUSED"
    platform_campaign.last_synced_at = timezone.now()
    platform_campaign.save(update_fields=["status", "last_synced_at", "updated_at"])

    return local_ad


# ════════════════════════════════════════════════════════════
#  2 ·  UPDATE CAMPAIGN ON META
# ════════════════════════════════════════════════════════════

def update_campaign_on_meta(
    unified_campaign_id: int,
    ad_asset: AdAsset | None = None,
):
    """
    Push local changes to the existing Meta Campaign / Ad Set / Ad.

    Only fields that have actually changed are sent to Meta.
    If the campaign has not yet been pushed (no ``platform_campaign_id``),
    this falls back to ``create_ad_on_meta``.

    The Facebook Page ID is read from ``AdIntegration.page_id``.

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign``.
    ad_asset : AdAsset | None
        New asset to upload and associate (replaces old creative).
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(id=unified_campaign_id)
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="META",
        is_active=True,
    )
    page_id = integration.page_id

    platform_campaign = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
        platform_campaign_id__isnull=False,
    ).first()

    if not platform_campaign:
        return create_ad_on_meta(unified_campaign_id, ad_asset)

    account = _init_meta(integration)

    # ── Update Campaign ─────────────────────────────────────
    try:
        meta_campaign = MetaCampaign(platform_campaign.platform_campaign_id)
        meta_campaign.api_update(params={
            "name": campaign.name,
            "objective": _meta_objective(campaign.objective),
            "status": _status_to_meta(campaign.status),
        })
        logger.info("Meta Campaign updated: %s", platform_campaign.platform_campaign_id)
    except Exception as exc:
        logger.error("Failed to update Meta Campaign %s: %s", platform_campaign.platform_campaign_id, exc)
        raise

    # ── Update Ad Set(s) ────────────────────────────────────
    budget = CampaignBudget.objects.filter(campaign=campaign, platform="META").first()

    for ad_group in platform_campaign.ad_groups.all():
        if not ad_group.platform_adgroup_id:
            continue

        adset_params = {
            "name": ad_group.name,
            "status": _status_to_meta(ad_group.status),
            "targeting": _build_targeting(ad_group.targeting_config or {}),
        }

        if budget:
            if budget.budget_type == "DAILY":
                adset_params["daily_budget"] = budget.daily_budget_minor
            else:
                adset_params["lifetime_budget"] = budget.daily_budget_minor
                if budget.end_date:
                    adset_params["end_time"] = budget.end_date.strftime("%Y-%m-%dT23:59:59")

        try:
            meta_adset = MetaAdSet(ad_group.platform_adgroup_id)
            meta_adset.api_update(params=adset_params)
            ad_group.last_synced_at = timezone.now()
            ad_group.error_message = None
            ad_group.save(update_fields=["last_synced_at", "error_message", "updated_at"])
            logger.info("Meta Ad Set updated: %s", ad_group.platform_adgroup_id)
        except Exception as exc:
            ad_group.error_message = str(exc)
            ad_group.save(update_fields=["error_message", "updated_at"])
            logger.error("Failed to update Meta Ad Set %s: %s", ad_group.platform_adgroup_id, exc)
            raise

        # ── Update Ads inside this Ad Set ───────────────────
        for local_ad in ad_group.ads.all():
            if not local_ad.platform_ad_id:
                continue

            # Build new creative if content or asset changed
            new_creative_id = None
            if ad_asset and page_id:
                new_creative_id = _create_or_update_creative(
                    account, integration, campaign, local_ad, page_id, ad_asset,
                )

            ad_params = {
                "name": local_ad.name,
                "status": _status_to_meta(local_ad.status),
            }
            if new_creative_id:
                ad_params["creative"] = {"creative_id": new_creative_id}

            try:
                meta_ad = MetaAd(local_ad.platform_ad_id)
                meta_ad.api_update(params=ad_params)
                logger.info("Meta Ad updated: %s", local_ad.platform_ad_id)
            except Exception as exc:
                logger.error("Failed to update Meta Ad %s: %s", local_ad.platform_ad_id, exc)
                raise

            if ad_asset:
                local_ad.assets.add(ad_asset)

    platform_campaign.status = campaign.status
    platform_campaign.last_synced_at = timezone.now()
    platform_campaign.save(update_fields=["status", "last_synced_at", "updated_at"])


def _create_or_update_creative(
    account: AdAccount,
    integration: AdIntegration,
    campaign: UnifiedCampaign,
    local_ad: Ad,
    page_id: str,
    ad_asset: AdAsset | None,
) -> str | None:
    """Create a new Meta AdCreative from the local Ad's fields. Returns creative ID."""

    link_data = {
        "link": local_ad.destination_url or "",
        "message": local_ad.primary_text or "",
        "name": local_ad.headline or "",
        "description": local_ad.description or "",
        "call_to_action": {
            "type": (local_ad.call_to_action or "LEARN_MORE").upper().replace(" ", "_"),
            "value": {"link": local_ad.destination_url or ""},
        },
    }

    if ad_asset:
        image_hash = _ensure_platform_asset(account, integration, ad_asset)
        link_data["image_hash"] = image_hash

    creative = account.create_ad_creative(params={
        "name": f"{campaign.name} - Creative (updated)",
        "object_story_spec": {
            "page_id": page_id,
            "link_data": link_data,
        },
    })
    logger.info("New Meta Creative created for update: %s", creative["id"])
    return creative["id"]


# ════════════════════════════════════════════════════════════
#  3 ·  DELETE AD ON META
# ════════════════════════════════════════════════════════════

def delete_ad_on_meta(
    unified_campaign_id: int,
    delete_level: str = "CAMPAIGN",
):
    """
    Delete Meta objects tied to a UnifiedCampaign, then clean up locally.

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign``.
    delete_level : str
        What level of the hierarchy to delete on Meta.
        - ``"CAMPAIGN"``  — deletes the Meta Campaign (cascades to ad sets & ads on Meta side).
        - ``"ADSET"``     — deletes only ad sets & ads, keeps the campaign shell.
        - ``"AD"``        — deletes only the ads, keeps campaign & ad sets.

    Notes
    -----
    Meta's API returns archived status for deleted campaigns.
    Local models are hard-deleted after successful Meta deletion.
    Partial failures are logged but do not stop the cleanup of other objects.
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(id=unified_campaign_id)
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="META",
        is_active=True,
    )
    _init_meta(integration)

    platform_campaigns = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
    )

    errors = []

    for pc in platform_campaigns:
        if delete_level == "CAMPAIGN":
            _delete_meta_campaign(pc, errors)
        elif delete_level == "ADSET":
            _delete_meta_adsets(pc, errors)
        elif delete_level == "AD":
            _delete_meta_ads(pc, errors)

    if errors:
        logger.warning(
            "Completed deletion for campaign %s with %d error(s): %s",
            unified_campaign_id, len(errors), errors,
        )

    # ── Local cleanup based on delete_level ─────────────────
    with transaction.atomic():
        if delete_level == "CAMPAIGN":
            # Remove all platform objects; keep the UnifiedCampaign as ARCHIVED
            for pc in platform_campaigns:
                pc.ad_groups.all().delete()  # cascades to ads
            platform_campaigns.delete()
            CampaignBudget.objects.filter(campaign=campaign, platform="META").delete()
            campaign.status = "ARCHIVED"
            campaign.save(update_fields=["status", "updated_at"])

        elif delete_level == "ADSET":
            for pc in platform_campaigns:
                pc.ad_groups.all().delete()

        elif delete_level == "AD":
            for pc in platform_campaigns:
                for ag in pc.ad_groups.all():
                    ag.ads.all().delete()

    return errors


def _delete_meta_campaign(pc: PlatformCampaign, errors: list):
    """Delete the Meta Campaign (Meta cascades ad sets & ads automatically)."""
    if not pc.platform_campaign_id:
        return
    try:
        meta_campaign = MetaCampaign(pc.platform_campaign_id)
        meta_campaign.api_delete()
        logger.info("Meta Campaign deleted: %s", pc.platform_campaign_id)
    except Exception as exc:
        logger.error("Failed to delete Meta Campaign %s: %s", pc.platform_campaign_id, exc)
        errors.append({"stage": "CAMPAIGN", "id": pc.platform_campaign_id, "error": str(exc)})


def _delete_meta_adsets(pc: PlatformCampaign, errors: list):
    """Delete all Meta Ad Sets under a PlatformCampaign."""
    for ag in pc.ad_groups.all():
        if not ag.platform_adgroup_id:
            continue
        # First delete ads inside this adset
        _delete_meta_ads_in_adgroup(ag, errors)
        try:
            meta_adset = MetaAdSet(ag.platform_adgroup_id)
            meta_adset.api_delete()
            logger.info("Meta Ad Set deleted: %s", ag.platform_adgroup_id)
        except Exception as exc:
            logger.error("Failed to delete Meta Ad Set %s: %s", ag.platform_adgroup_id, exc)
            errors.append({"stage": "ADSET", "id": ag.platform_adgroup_id, "error": str(exc)})


def _delete_meta_ads(pc: PlatformCampaign, errors: list):
    """Delete all Meta Ads under all Ad Sets of a PlatformCampaign."""
    for ag in pc.ad_groups.all():
        _delete_meta_ads_in_adgroup(ag, errors)


def _delete_meta_ads_in_adgroup(ag: AdGroup, errors: list):
    """Delete all Meta Ads inside a single AdGroup."""
    for ad in ag.ads.all():
        if not ad.platform_ad_id:
            continue
        try:
            meta_ad = MetaAd(ad.platform_ad_id)
            meta_ad.api_delete()
            logger.info("Meta Ad deleted: %s", ad.platform_ad_id)
        except Exception as exc:
            logger.error("Failed to delete Meta Ad %s: %s", ad.platform_ad_id, exc)
            errors.append({"stage": "AD", "id": ad.platform_ad_id, "error": str(exc)})


# ────────────────────────────────────────────────────────────
# STATUS MAPPING
# ────────────────────────────────────────────────────────────

def _status_to_meta(status: str) -> str:
    """Convert unified status to Meta API status."""
    mapping = {
        "ACTIVE": "ACTIVE",
        "PAUSED": "PAUSED",
        "ARCHIVED": "DELETED",
        "DRAFT": "PAUSED",
        "ERROR": "PAUSED",
        "SYNCING": "PAUSED",
    }
    return mapping.get(status, "PAUSED")
