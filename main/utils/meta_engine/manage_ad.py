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
    account_id = (integration.ad_account_id or "").strip()
    if account_id and not account_id.startswith("act_"):
        account_id = f"act_{account_id}"
    return AdAccount(account_id)


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

OBJECTIVE_ADSET_RULES = {
    "CONVERSIONS": {
        "optimization_goals": ["OFFSITE_CONVERSIONS", "LINK_CLICKS", "REACH"],
        "billing_events": ["IMPRESSIONS", "LINK_CLICKS"],
    },
    "TRAFFIC": {
        "optimization_goals": ["LINK_CLICKS", "LANDING_PAGE_VIEWS", "REACH"],
        "billing_events": ["LINK_CLICKS", "IMPRESSIONS"],
    },
    "LEADS": {
        "optimization_goals": ["LEAD_GENERATION", "LINK_CLICKS", "REACH"],
        "billing_events": ["IMPRESSIONS", "LINK_CLICKS"],
    },
    "LEAD_GENERATION": {
        "optimization_goals": ["LEAD_GENERATION", "LINK_CLICKS", "REACH"],
        "billing_events": ["IMPRESSIONS", "LINK_CLICKS"],
    },
    "AWARENESS": {
        "optimization_goals": ["REACH", "IMPRESSIONS", "LINK_CLICKS"],
        "billing_events": ["IMPRESSIONS"],
    },
    "ENGAGEMENT": {
        "optimization_goals": ["POST_ENGAGEMENT", "LINK_CLICKS", "REACH"],
        "billing_events": ["IMPRESSIONS", "POST_ENGAGEMENT"],
    },
    "APP_PROMOTION": {
        "optimization_goals": ["APP_INSTALLS", "LINK_CLICKS", "REACH"],
        "billing_events": ["APP_INSTALLS", "IMPRESSIONS"],
    },
}

EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
    "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO",
}


def _meta_objective(unified_objective: str) -> str:
    return OBJECTIVE_TO_META.get(unified_objective, "OUTCOME_TRAFFIC")


def _optimization_goal(unified_objective: str) -> str:
    return OPTIMIZATION_GOAL_MAP.get(unified_objective, "LINK_CLICKS")


def _optimization_goal_candidates(unified_objective: str) -> list[str]:
    """Return ordered optimization-goal candidates for resilient adset creation."""
    primary = _optimization_goal(unified_objective)
    rule_goals = OBJECTIVE_ADSET_RULES.get(unified_objective, {}).get(
        "optimization_goals", ["LINK_CLICKS", "REACH"]
    )
    goals = [primary] + list(rule_goals)

    # De-duplicate while preserving order.
    seen = set()
    ordered: list[str] = []
    for goal in goals:
        if goal and goal not in seen:
            seen.add(goal)
            ordered.append(goal)
    return ordered


def _billing_event_candidates(unified_objective: str, optimization_goal: str) -> list[str]:
    """Return ordered billing-event candidates for a given objective/goal pair."""
    defaults = OBJECTIVE_ADSET_RULES.get(unified_objective, {}).get(
        "billing_events", ["IMPRESSIONS"]
    )
    candidates = list(defaults)

    # Keep billing event aligned with key optimization goals when possible.
    if optimization_goal == "LINK_CLICKS":
        candidates = ["LINK_CLICKS"] + candidates
    elif optimization_goal == "POST_ENGAGEMENT":
        candidates = ["POST_ENGAGEMENT"] + candidates
    elif optimization_goal == "APP_INSTALLS":
        candidates = ["APP_INSTALLS"] + candidates

    # De-duplicate while preserving order.
    seen = set()
    ordered = []
    for event in candidates:
        if event and event not in seen:
            seen.add(event)
            ordered.append(event)
    return ordered


def _create_adset_with_goal_fallback(
    account: AdAccount,
    adset_params_base: dict,
    unified_objective: str,
):
    """Create Meta ad set by trying compatible optimization goals + billing events."""
    last_exc = None
    tried: list[str] = []
    for goal in _optimization_goal_candidates(unified_objective):
        for billing_event in _billing_event_candidates(unified_objective, goal):
            params = {
                **adset_params_base,
                "optimization_goal": goal,
                "billing_event": billing_event,
            }
            tried.append(f"{goal}:{billing_event}")
            try:
                meta_adset = account.create_ad_set(params=params)
                return meta_adset, goal, billing_event
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Meta adset create failed for optimization_goal=%s billing_event=%s: %s",
                    goal,
                    billing_event,
                    exc,
                )

    raise ValueError(
        f"Failed to create ad set for objective={unified_objective}. Tried optimization goals: {tried}. Last error: {last_exc}"
    )


def _is_performance_goal_unavailable_error(exc: Exception) -> bool:
    text = str(exc)
    lowered = text.lower()
    return (
        "performance goal isn't available" in lowered
        or "error_subcode\": 2490408" in text
        or 'blame_field_specs\\\":[[\\\"optimization_goal\\\"]]' in text
    )


def _create_meta_campaign_with_objective(
    account: AdAccount,
    campaign: UnifiedCampaign,
    meta_objective: str,
):
    return account.create_campaign(params={
        "name": campaign.name,
        "objective": meta_objective,
        "status": "PAUSED",
        "special_ad_categories": [],
        "is_adset_budget_sharing_enabled": False,
    })


def _create_adset_resilient(
    account: AdAccount,
    adset_params_base: dict,
    unified_objective: str,
    campaign: UnifiedCampaign,
    platform_campaign: PlatformCampaign | None = None,
):
    """Create adset with optimization fallback and ENGAGEMENT->TRAFFIC campaign fallback."""
    try:
        meta_adset, used_goal, used_billing_event = _create_adset_with_goal_fallback(
            account,
            adset_params_base,
            unified_objective,
        )
        return meta_adset, used_goal, used_billing_event
    except Exception as exc:
        if unified_objective == "ENGAGEMENT" and _is_performance_goal_unavailable_error(exc):
            logger.warning(
                "Meta objective fallback triggered for campaign %s: %s",
                campaign.id,
                exc,
            )

            fallback_campaign = _create_meta_campaign_with_objective(
                account,
                campaign,
                "OUTCOME_TRAFFIC",
            )
            fallback_campaign_id = fallback_campaign["id"]

            if platform_campaign:
                platform_campaign.platform_campaign_id = fallback_campaign_id
                platform_campaign.status = "PAUSED"
                platform_campaign.last_synced_at = timezone.now()
                platform_campaign.save(update_fields=["platform_campaign_id", "status", "last_synced_at", "updated_at"])

            fallback_params = {**adset_params_base, "campaign_id": fallback_campaign_id}
            return _create_adset_with_goal_fallback(account, fallback_params, "TRAFFIC")

        raise


def _build_promoted_object(page_id: str, unified_objective: str, draft: dict | None = None) -> dict:
    """Build promoted_object with objective-aware optional fields.

    Request contract is unchanged: this reads from existing draft fields when present.
    """
    draft = draft or {}
    promoted = {"page_id": str(page_id)}

    # For conversion-oriented objectives, include optional conversion context
    # if already present in existing backend draft payload.
    if unified_objective == "CONVERSIONS":
        pixel_id = draft.get("pixel_id")
        custom_conversion_id = draft.get("custom_conversion_id")
        event_name = draft.get("event_name")
        if pixel_id:
            promoted["pixel_id"] = str(pixel_id)
        if custom_conversion_id:
            promoted["custom_conversion_id"] = str(custom_conversion_id)
        if event_name:
            promoted["custom_event_type"] = str(event_name)

    return promoted


# ────────────────────────────────────────────────────────────
# CTA MAPPING  (internal / legacy → valid Meta CTA)
# ────────────────────────────────────────────────────────────

CTA_TO_META = {
    "READ_MORE":       "LEARN_MORE",
    "GET_STARTED":     "LEARN_MORE",
    "FIND_OUT_MORE":   "LEARN_MORE",
    "BUY":             "BUY_NOW",
    "PURCHASE":        "BUY_NOW",
    "REGISTER":        "SIGN_UP",
    "SIGNUP":          "SIGN_UP",
    "SIGN_UP":         "SIGN_UP",
    "BOOK":            "BOOK_NOW",
    "CALL":            "CALL_NOW",
    "DOWNLOAD":        "DOWNLOAD",
    "LEARN_MORE":      "LEARN_MORE",
    "SHOP_NOW":        "SHOP_NOW",
    "CONTACT_US":      "CONTACT_US",
    "SUBSCRIBE":       "SUBSCRIBE",
    "APPLY_NOW":       "APPLY_NOW",
    "GET_QUOTE":       "GET_QUOTE",
    "ORDER_NOW":       "ORDER_NOW",
    "SEND_MESSAGE":    "MESSAGE_PAGE",
    "WHATSAPP":        "WHATSAPP_MESSAGE",
    "WATCH_VIDEO":     "WATCH_VIDEO",
    "GET_DIRECTIONS":  "GET_DIRECTIONS",
    "SEE_MENU":        "SEE_MENU",
    "LISTEN_NOW":      "LISTEN_NOW",
}


def _normalize_cta(raw_cta: str | None) -> str:
    """Convert an internal CTA value to a valid Meta API call_to_action type."""
    if not raw_cta:
        return "LEARN_MORE"
    key = str(raw_cta).upper().replace(" ", "_").strip()
    mapped = CTA_TO_META.get(key, key)
    valid_meta_cta = {
        "OPEN_LINK", "LIKE_PAGE", "SHOP_NOW", "PLAY_GAME", "INSTALL_APP", "USE_APP",
        "CALL", "VIDEO_CALL", "INSTALL_MOBILE_APP", "USE_MOBILE_APP", "LEARN_MORE",
        "SIGN_UP", "DOWNLOAD", "NO_BUTTON", "CALL_NOW", "APPLY_NOW", "CONTACT",
        "BUY_NOW", "GET_OFFER", "BUY_TICKETS", "GET_DIRECTIONS", "BUY", "MESSAGE_PAGE",
        "SUBSCRIBE", "DONATE", "DONATE_NOW", "GET_QUOTE", "CONTACT_US", "ORDER_NOW",
        "START_ORDER", "ADD_TO_CART", "WHATSAPP_MESSAGE", "WATCH_VIDEO", "LISTEN_NOW",
        "SEE_MENU", "BOOK_NOW", "GET_SHOWTIMES",
    }
    return mapped if mapped in valid_meta_cta else "LEARN_MORE"


def _extract_country_codes(targeting_config: dict) -> list[str]:
    targeting_config = targeting_config or {}
    locations = targeting_config.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    codes = [_normalize_country(loc) for loc in locations]
    return [code for code in codes if code]


def _is_eu_targeting(targeting_config: dict) -> bool:
    codes = _extract_country_codes(targeting_config)
    return any(code in EU_COUNTRY_CODES for code in codes)


def _resolve_dsa_fields(account: AdAccount, targeting_config: dict) -> dict:
    """Return DSA payor/beneficiary fields for EU targeting when available."""
    if not _is_eu_targeting(targeting_config):
        return {}

    payor = getattr(settings, "META_DEFAULT_DSA_PAYOR", None)
    beneficiary = getattr(settings, "META_DEFAULT_DSA_BENEFICIARY", None)

    try:
        account_defaults = account.api_get(fields=["default_dsa_payor", "default_dsa_beneficiary"])
        if isinstance(account_defaults, dict):
            payor = payor or account_defaults.get("default_dsa_payor")
            beneficiary = beneficiary or account_defaults.get("default_dsa_beneficiary")
    except Exception as exc:
        # Non-fatal: we still allow caller-provided settings fallback.
        logger.warning("Unable to fetch ad-account DSA defaults: %s", exc)

    if payor and beneficiary:
        return {"dsa_payor": str(payor), "dsa_beneficiary": str(beneficiary)}

    raise ValueError(
        "EU targeting detected but DSA payor/beneficiary is not configured. "
        "Set account defaults in Meta or configure META_DEFAULT_DSA_PAYOR / META_DEFAULT_DSA_BENEFICIARY."
    )


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


def _normalize_country(value: str | None) -> str:
    """Convert a country name or code to a 2-letter ISO code for Meta."""
    if not value:
        return ""

    v = str(value).strip()
    if not v:
        return ""

    # Already a 2-letter code
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return _COUNTRY_NAME_TO_CODE.get(v.lower(), v.upper()[:2])


def _build_targeting(targeting_config: dict) -> dict:
    """Convert our normalised targeting into Meta's targeting spec."""
    targeting_config = targeting_config or {}
    targeting = {}

    locations = targeting_config.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]

    if locations:
        codes = [_normalize_country(loc) for loc in locations]
        codes = [code for code in codes if code]
        if codes:
            targeting["geo_locations"] = {"countries": codes}

    age_min = targeting_config.get("min_age")
    age_max = targeting_config.get("max_age")
    if age_min:
        targeting["age_min"] = int(age_min)
    if age_max:
        targeting["age_max"] = int(age_max)

    gender = str(targeting_config.get("gender") or "").strip().lower()
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

    if campaign.objective not in OBJECTIVE_TO_META:
        raise MetaAdCreationError(
            "VALIDATION",
            f"Unsupported objective '{campaign.objective}' for Meta campaign creation.",
        )

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
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "start_time": start_time,
            "status": "PAUSED",
            "targeting": _build_targeting(targeting_config),
            "promoted_object": _build_promoted_object(page_id, campaign.objective, draft),
        }

        try:
            adset_params.update(_resolve_dsa_fields(account, targeting_config))
        except ValueError as exc:
            raise MetaAdCreationError("VALIDATION", str(exc), platform_campaign=platform_campaign) from exc

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
            meta_adset, used_goal, used_billing_event = _create_adset_resilient(
                account,
                adset_params,
                campaign.objective,
                campaign,
                platform_campaign,
            )
            meta_adset_id = meta_adset["id"]
            logger.info(
                "Meta Ad Set created: %s (optimization_goal=%s, billing_event=%s)",
                meta_adset_id,
                used_goal,
                used_billing_event,
            )
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

        # promoted_object is immutable for many Meta ad sets.
        # If an older ad set has no promoted_object, recreate it instead of updating.
        needs_recreate = False
        try:
            existing_adset = MetaAdSet(meta_adset_id).api_get(fields=["promoted_object"])
            promoted_object = None
            if existing_adset:
                if isinstance(existing_adset, dict):
                    promoted_object = existing_adset.get("promoted_object")
                else:
                    # If SDK type is not dict-like, treat as unknown and recreate.
                    promoted_object = None
            if not promoted_object or not promoted_object.get("page_id"):
                needs_recreate = True
        except Exception as exc:
            logger.warning(
                "Could not read promoted_object for ad set %s (%s); recreating ad set.",
                meta_adset_id,
                exc,
            )
            needs_recreate = True

        if needs_recreate:
            targeting_config = ad_group.targeting_config or {}
            start_time = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S")
            replacement_adset_params = {
                "name": ad_group.name or f"{campaign.name} - Ad Set",
                "campaign_id": meta_campaign_id,
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "start_time": start_time,
                "status": "PAUSED",
                "targeting": _build_targeting(targeting_config),
                "promoted_object": _build_promoted_object(page_id, campaign.objective, draft),
            }

            try:
                replacement_adset_params.update(_resolve_dsa_fields(account, targeting_config))
            except ValueError as exc:
                raise MetaAdCreationError("VALIDATION", str(exc), platform_campaign=platform_campaign, ad_group=ad_group) from exc

            if budget:
                if budget.budget_type == "DAILY":
                    replacement_adset_params["daily_budget"] = budget.daily_budget_minor
                else:
                    replacement_adset_params["lifetime_budget"] = budget.daily_budget_minor
                    if budget.end_date and budget.end_date > datetime.now().date():
                        replacement_adset_params["end_time"] = budget.end_date.strftime("%Y-%m-%dT23:59:59")
                    else:
                        fallback_end = datetime.now() + timedelta(days=30)
                        replacement_adset_params["end_time"] = fallback_end.strftime("%Y-%m-%dT23:59:59")

            old_meta_adset_id = meta_adset_id
            try:
                replacement_adset, used_goal, used_billing_event = _create_adset_resilient(
                    account,
                    replacement_adset_params,
                    campaign.objective,
                    campaign,
                    platform_campaign,
                )
                meta_adset_id = replacement_adset["id"]
            except Exception as exc:
                raise MetaAdCreationError(
                    "ADSET", f"Failed to recreate ad set with promoted_object: {exc}",
                    platform_campaign=platform_campaign,
                    ad_group=ad_group,
                ) from exc

            ad_group.platform_adgroup_id = meta_adset_id
            ad_group.status = "PAUSED"
            ad_group.last_synced_at = timezone.now()
            ad_group.save(update_fields=["platform_adgroup_id", "status", "last_synced_at", "updated_at"])
            logger.info(
                "Recreated Meta Ad Set with promoted_object. Old=%s New=%s goal=%s billing=%s",
                old_meta_adset_id,
                meta_adset_id,
                used_goal,
                used_billing_event,
            )

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
            "type": _normalize_cta(cta),
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
            "type": _normalize_cta(local_ad.call_to_action or "LEARN_MORE"),
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


# ────────────────────────────────────────────────────────────
# TOGGLE CAMPAIGN STATUS (PAUSE / RESUME)
# ────────────────────────────────────────────────────────────

def toggle_campaign_status_on_meta(unified_campaign_id: int, target_status: str) -> list[dict]:
    """
    Set all Meta objects belonging to *unified_campaign_id* to *target_status*
    ("ACTIVE" or "PAUSED").

    Updates PlatformCampaign, AdGroup, and Ad rows in the DB to match.
    Returns a list of error dicts (empty list = full success).
    """
    from main.models import UnifiedCampaign, PlatformCampaign

    if target_status not in ("ACTIVE", "PAUSED"):
        raise ValueError(f"target_status must be ACTIVE or PAUSED, got {target_status!r}")

    campaign = UnifiedCampaign.objects.get(id=unified_campaign_id)
    meta_status = _status_to_meta(target_status)
    errors: list[dict] = []

    platform_campaigns = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration__platform="META",
    ).select_related("integration").prefetch_related("ad_groups__ads")

    for pc in platform_campaigns:
        integration = pc.integration
        try:
            _init_meta(integration)
        except Exception as exc:
            errors.append({"stage": "INIT", "platform_campaign_id": pc.id, "error": str(exc)})
            continue

        # ── Campaign level ─────────────────────────────────
        if pc.platform_campaign_id:
            try:
                meta_campaign = MetaCampaign(pc.platform_campaign_id)
                meta_campaign.api_update(params={"status": meta_status})
                pc.status = target_status
                pc.save(update_fields=["status"])
                logger.info("Meta campaign %s set to %s", pc.platform_campaign_id, meta_status)
            except Exception as exc:
                logger.error("Failed to update Meta campaign %s: %s", pc.platform_campaign_id, exc)
                errors.append({"stage": "CAMPAIGN", "id": pc.platform_campaign_id, "error": str(exc)})

        # ── Ad Set level ───────────────────────────────────
        for ag in pc.ad_groups.all():
            if ag.platform_adgroup_id:
                try:
                    meta_adset = MetaAdSet(ag.platform_adgroup_id)
                    meta_adset.api_update(params={"status": meta_status})
                    ag.status = target_status
                    ag.save(update_fields=["status"])
                except Exception as exc:
                    logger.error("Failed to update Meta ad set %s: %s", ag.platform_adgroup_id, exc)
                    errors.append({"stage": "ADSET", "id": ag.platform_adgroup_id, "error": str(exc)})

            # ── Ad level ───────────────────────────────────
            for ad in ag.ads.all():
                if ad.platform_ad_id:
                    try:
                        meta_ad = MetaAd(ad.platform_ad_id)
                        meta_ad.api_update(params={"status": meta_status})
                        ad.status = target_status
                        ad.save(update_fields=["status"])
                    except Exception as exc:
                        logger.error("Failed to update Meta ad %s: %s", ad.platform_ad_id, exc)
                        errors.append({"stage": "AD", "id": ad.platform_ad_id, "error": str(exc)})

    return errors
