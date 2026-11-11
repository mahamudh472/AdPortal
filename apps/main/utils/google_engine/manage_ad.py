"""
Google Ads Management — Create, Update, Delete, Toggle Status

Each function is designed to be **resumable**: if a step fails, previously
created platform objects are reused on retry instead of being recreated.

Hierarchy (Google Ads → local model):
    Campaign      → PlatformCampaign
    Ad Group      → AdGroup
    Ad            → Ad

Google Ads REST API v18:
    https://developers.google.com/google-ads/api/rest/reference/rest

All money values coming *in* to these functions are expected in
**minor units** (micros for Google = 1/1,000,000 of the currency unit,
but stored as cents/minor in CampaignBudget). We convert to micros on write.

Authentication: OAuth2 access_token stored in AdIntegration.access_token,
with refresh via AdIntegration.refresh_token.
Developer token: settings.GOOGLE_ADS_DEVELOPER_TOKEN
Customer ID (ad account): integration.ad_account_id  (digits only, no dashes)
"""

import logging
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.main.models import (
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

GOOGLE_ADS_API_VERSION = (
    str(getattr(settings, "GOOGLE_ADS_API_VERSION", "v18"))
    .strip().strip('"').strip("'")
)
if not GOOGLE_ADS_API_VERSION.startswith("v"):
    GOOGLE_ADS_API_VERSION = f"v{GOOGLE_ADS_API_VERSION}"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"


# ────────────────────────────────────────────────────────────
# HTTP HELPERS
# ────────────────────────────────────────────────────────────

def _manager_id() -> str | None:
    """Return the manager ID from settings, handling test mode."""
    if getattr(settings, "GOOGLE_ADS_USE_TEST_ACCOUNT", False):
        mid = getattr(settings, "GOOGLE_ADS_TEST_MANAGER_ID", None)
    else:
        mid = getattr(settings, "GOOGLE_ADS_MANAGER_ID", None)
    
    if mid:
        return str(mid).replace("-", "")
    return None


def _get_login_customer_id(access_token: str) -> str | None:
    """Resolve the login customer ID for the given access token, falling back to settings."""
    try:
        integration = AdIntegration.find_by_token(access_token)
        if integration and integration.manager_id:
            return str(integration.manager_id).replace("-", "")
    except Exception:
        pass
    return _manager_id()


def _headers(access_token: str, login_customer_id: str | None = None) -> dict:
    if login_customer_id is None:
        login_customer_id = _get_login_customer_id(access_token)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = str(login_customer_id).replace("-", "")
    return headers


def _customer_id(integration: AdIntegration) -> str:
    """Return the customer ID stripped of dashes."""
    return str(integration.ad_account_id).replace("-", "")


def _refresh_access_token(integration: AdIntegration) -> str:
    """
    Use the stored refresh_token to obtain a new access_token.
    Updates the integration in-place and in the DB.
    """
    if not integration.refresh_token:
        raise GoogleAdError(
            "AUTH",
            "No refresh_token stored. Re-connect the Google integration.",
        )

    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": integration.refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        raise GoogleAdError("AUTH", f"Token refresh failed: {data}")

    new_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    integration.access_token = new_token
    integration.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    integration.save(update_fields=["access_token", "token_expires_at"])
    logger.info("Google access token refreshed for integration %s", integration.id)
    return new_token


def _get_valid_token(integration: AdIntegration) -> str:
    """Return a valid access token, refreshing if expired or close to expiry."""
    if integration.token_expires_at and timezone.now() >= (
        integration.token_expires_at - timedelta(minutes=5)
    ):
        return _refresh_access_token(integration)
    return integration.access_token


def _google_get(url: str, access_token: str, login_customer_id: str | None = None, params: dict | None = None) -> dict:
    """GET from the Google Ads REST API."""
    resp = requests.get(
        url, 
        headers=_headers(access_token, login_customer_id), 
        params=params, 
        timeout=30
    )
    if not resp.ok:
        raise RuntimeError(
            f"Google Ads API GET {url} failed [{resp.status_code}]: {resp.text}"
        )
    return resp.json()


# ────────────────────────────────────────────────────────────
# OBJECTIVE / STATUS MAPPINGS
# ────────────────────────────────────────────────────────────

OBJECTIVE_TO_GOOGLE = {
    "CONVERSIONS":      "SEARCH",
    "TRAFFIC":          "SEARCH",
    "LEADS":            "LEAD_GENERATION",
    "AWARENESS":        "DISPLAY",
    "ENGAGEMENT":       "DISPLAY",
    "APP_PROMOTION":    "APP",
    "LEAD_GENERATION":  "LEAD_GENERATION",
}

OBJECTIVE_TO_BIDDING = {
    "CONVERSIONS":      "TARGET_CPA",
    "TRAFFIC":          "MAXIMIZE_CLICKS",
    "LEADS":            "MAXIMIZE_CONVERSIONS",
    "AWARENESS":        "TARGET_IMPRESSION_SHARE",
    "ENGAGEMENT":       "MAXIMIZE_CLICKS",
    "APP_PROMOTION":    "MAXIMIZE_CONVERSIONS",
    "LEAD_GENERATION":  "MAXIMIZE_CONVERSIONS",
}

UNIFIED_TO_GOOGLE_STATUS = {
    "ACTIVE":   "ENABLED",
    "PAUSED":   "PAUSED",
    "ARCHIVED": "REMOVED",
    "DRAFT":    "PAUSED",
    "ERROR":    "PAUSED",
}

GOOGLE_STATUS_TO_UNIFIED = {
    "ENABLED": "ACTIVE",
    "PAUSED":  "PAUSED",
    "REMOVED": "ARCHIVED",
}


def _google_campaign_type(objective: str) -> str:
    return OBJECTIVE_TO_GOOGLE.get(objective, "SEARCH")


def _bidding_strategy(objective: str) -> str:
    return OBJECTIVE_TO_BIDDING.get(objective, "MAXIMIZE_CLICKS")


def _status_to_google(status: str) -> str:
    return UNIFIED_TO_GOOGLE_STATUS.get(status, "PAUSED")


# ────────────────────────────────────────────────────────────
# BUDGET HELPERS
# ────────────────────────────────────────────────────────────

def _minor_to_micros(minor_units: int) -> int:
    """Convert cents (minor units) → micros (Google Ads unit)."""
    return int(minor_units) * 10_000   # 1 cent = 10,000 micros


# ────────────────────────────────────────────────────────────
# TARGETING HELPERS
# ────────────────────────────────────────────────────────────

# Common country name → ISO 3166-1 alpha-2 code
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

# Google Ads Criterion ID for countries (geo target constants)
# These are the canonical resource names — we'll use country codes via
# geo_target_constants query instead.

def _normalize_country(value: str) -> str:
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return _COUNTRY_NAME_TO_CODE.get(v.lower(), v.upper()[:2])


# ════════════════════════════════════════════════════════════
#  EXCEPTION CLASS
# ════════════════════════════════════════════════════════════

class GoogleAdError(Exception):
    """Raised when a Google Ads API call fails during ad management."""

    def __init__(self, stage: str, message: str, platform_campaign=None, ad_group=None):
        self.stage = stage
        self.platform_campaign = platform_campaign
        self.ad_group = ad_group
        super().__init__(f"[{stage}] {message}")


# ════════════════════════════════════════════════════════════
#  1 ·  CREATE AD ON GOOGLE
# ════════════════════════════════════════════════════════════

def create_ad_on_google(
    unified_campaign_id: int,
    ad_asset: AdAsset | None = None,
):
    """
    Push a full ad stack (Campaign Budget → Campaign → Ad Group → Ad) to Google Ads.

    Designed for **resumability**: if a previous attempt partially succeeded,
    existing objects are reused instead of creating duplicates.

    Google Ads REST hierarchy:
        CampaignBudget  →  Campaign  →  AdGroup  →  Ad

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign`` to publish.
    ad_asset : AdAsset | None
        Optional image/video asset to include.

    Returns
    -------
    Ad
        The local ``Ad`` model instance.

    Raises
    ------
    GoogleAdError
        With ``.stage`` indicating where the failure occurred.
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(
        id=unified_campaign_id
    )
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="GOOGLE",
        is_active=True,
    )

    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    budget = CampaignBudget.objects.filter(campaign=campaign, platform="GOOGLE").first()
    draft = campaign.draft_data or {}

    # Determine budget amount in micros
    daily_budget_micros = 0
    if budget:
        daily_budget_micros = _minor_to_micros(budget.daily_budget_minor)
    else:
        draft_budgets = draft.get("budgets", [])
        google_budget = next(
            (b for b in draft_budgets if b.get("platform") == "GOOGLE"), None
        )
        if google_budget:
            daily_budget_micros = int(google_budget["budget"]) * 10_000

    if not daily_budget_micros:
        daily_budget_micros = 1_000_000  # default $1/day

    # ── Step 1: PlatformCampaign (Google Campaign) ───────────
    platform_campaign = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
    ).first()

    if not platform_campaign or not platform_campaign.platform_campaign_id:
        try:
            # Create campaign budget resource first
            budget_url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaignBudgets:mutate"
            budget_resp = _google_post(token, budget_url, {
                "operations": [{
                    "create": {
                        "name": f"{campaign.name} - Budget",
                        "amount_micros": str(daily_budget_micros),
                        "delivery_method": "STANDARD",
                        "explicitly_shared": False,
                    }
                }]
            })
            budget_resource = (
                budget_resp.get("results", [{}])[0]
                .get("resourceName", "")
            )
            logger.info("Google Campaign Budget created: %s", budget_resource)

            # Create the campaign
            campaign_url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaigns:mutate"
            campaign_payload = {
                "operations": [{
                    "create": {
                        "name": campaign.name,
                        "status": "PAUSED",
                        "advertising_channel_type": _google_campaign_type(campaign.objective),
                        "campaign_budget": budget_resource,
                        "manual_cpc": {},
                        "network_settings": {
                            "target_google_search": True,
                            "target_search_network": True,
                            "target_content_network": False,
                        },
                        # Required field in v20
                        "contains_eu_political_advertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
                    }
                }]
            }

            campaign_resp = _google_post(token, campaign_url, campaign_payload)
            google_campaign_resource = (
                campaign_resp.get("results", [{}])[0]
                .get("resourceName", "")
            )
            # Resource name format: customers/{cid}/campaigns/{campaign_id}
            google_campaign_id = google_campaign_resource.split("/")[-1]
            logger.info("Google Campaign created: %s (id=%s)", google_campaign_resource, google_campaign_id)

        except Exception as exc:
            raise GoogleAdError("CAMPAIGN", str(exc)) from exc

        if platform_campaign:
            platform_campaign.platform_campaign_id = google_campaign_id
            platform_campaign.status = "PAUSED"
            platform_campaign.last_synced_at = timezone.now()
            platform_campaign.extra_data = {"budget_resource": budget_resource}
            platform_campaign.save()
        else:
            platform_campaign = PlatformCampaign.objects.create(
                unified_campaign=campaign,
                integration=integration,
                platform_campaign_id=google_campaign_id,
                status="PAUSED",
                last_synced_at=timezone.now(),
                extra_data={"budget_resource": budget_resource},
            )
    else:
        google_campaign_id = platform_campaign.platform_campaign_id
        logger.info("Reusing existing Google Campaign: %s", google_campaign_id)

    # ── Step 2: Ad Group ─────────────────────────────────────
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

        # Default CPC bid: $1 (1,000,000 micros)
        cpc_bid_micros = 1_000_000

        try:
            adgroup_url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroups:mutate"
            adgroup_resp = _google_post(token, adgroup_url, {
                "operations": [{
                    "create": {
                        "name": f"{campaign.name} - Ad Group",
                        "campaign": f"customers/{cid}/campaigns/{google_campaign_id}",
                        "status": "ENABLED",
                        "type": "SEARCH_STANDARD",
                        "cpc_bid_micros": str(cpc_bid_micros),
                    }
                }]
            })
            google_adgroup_resource = (
                adgroup_resp.get("results", [{}])[0]
                .get("resourceName", "")
            )
            google_adgroup_id = google_adgroup_resource.split("/")[-1]
            logger.info("Google Ad Group created: %s", google_adgroup_resource)
        except Exception as exc:
            raise GoogleAdError(
                "ADGROUP", str(exc), platform_campaign=platform_campaign
            ) from exc

        # Add keyword criteria if provided
        keywords = targeting_config.get("keywords") or []
        if keywords:
            _add_keywords_to_adgroup(token, cid, google_adgroup_id, keywords)

        if ad_group:
            ad_group.platform_adgroup_id = google_adgroup_id
            ad_group.status = "ACTIVE"
            ad_group.last_synced_at = timezone.now()
            ad_group.save()
        else:
            ad_group = AdGroup.objects.create(
                platform_campaign=platform_campaign,
                name=f"{campaign.name} - Ad Group",
                platform_adgroup_id=google_adgroup_id,
                status="ACTIVE",
                targeting_config=targeting_config,
                last_synced_at=timezone.now(),
            )
    else:
        google_adgroup_id = ad_group.platform_adgroup_id
        logger.info("Reusing existing Google Ad Group: %s", google_adgroup_id)

    # ── Step 3: Ad ───────────────────────────────────────────
    local_ad = Ad.objects.filter(ad_group=ad_group).first()

    if local_ad and local_ad.platform_ad_id:
        logger.info("Reusing existing Google Ad: %s", local_ad.platform_ad_id)
        return local_ad

    headline = draft.get("headline", "") if not local_ad else (local_ad.headline or "")
    description = draft.get("description", "") if not local_ad else (local_ad.description or "")
    destination_url = draft.get("destination_url", "") if not local_ad else (local_ad.destination_url or "")
    ad_name = draft.get("ad_name", f"{campaign.name} - Ad")
    if local_ad and local_ad.name:
        ad_name = local_ad.name

    # Split headline into max 3 parts of 30 chars each for Google RSA
    headlines = _split_headlines(headline)
    descriptions = _split_descriptions(description)

    try:
        adgroupad_url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroupAds:mutate"
        ad_payload = {
            "operations": [{
                "create": {
                    "ad_group": f"customers/{cid}/adGroups/{google_adgroup_id}",
                    "status": "PAUSED",
                    "ad": {
                        "name": ad_name,
                        "final_urls": [destination_url] if destination_url else ["https://example.com"],
                        "responsive_search_ad": {
                            "headlines": [
                                {"text": h[:30]}
                                for h in headlines
                            ],
                            "descriptions": [
                                {"text": d[:90]} for d in descriptions
                            ],
                        },
                    },
                }
            }]
        }
        ad_resp = _google_post(token, adgroupad_url, ad_payload)
        google_adgroupad_resource = (
            ad_resp.get("results", [{}])[0]
            .get("resourceName", "")
        )
        # Resource name format: customers/{cid}/adGroupAds/{adgroup_id}~{ad_id}
        google_ad_id = google_adgroupad_resource.split("~")[-1] if "~" in google_adgroupad_resource else google_adgroupad_resource.split("/")[-1]
        logger.info("Google AdGroupAd created: %s", google_adgroupad_resource)
    except Exception as exc:
        raise GoogleAdError(
            "AD", str(exc),
            platform_campaign=platform_campaign,
            ad_group=ad_group,
        ) from exc

    # Persist local Ad
    primary_text = draft.get("primary_text", "") if not local_ad else (local_ad.primary_text or "")
    cta = draft.get("call_to_action", "") if not local_ad else (local_ad.call_to_action or "")

    if local_ad:
        local_ad.platform_ad_id = google_ad_id
        local_ad.status = "PAUSED"
        local_ad.save()
    else:
        local_ad = Ad.objects.create(
            ad_group=ad_group,
            name=ad_name,
            platform_ad_id=google_ad_id,
            status="PAUSED",
            headline=headline,
            primary_text=primary_text,
            description=description,
            destination_url=destination_url,
            call_to_action=cta,
        )

    if ad_asset:
        local_ad.assets.add(ad_asset)

    # Mark campaign active
    campaign.status = "ACTIVE"
    campaign.draft_data = {}
    campaign.save(update_fields=["status", "draft_data", "updated_at"])

    platform_campaign.status = "PAUSED"
    platform_campaign.last_synced_at = timezone.now()
    platform_campaign.save(update_fields=["status", "last_synced_at", "updated_at"])

    return local_ad


# ────────────────────────────────────────────────────────────
# KEYWORD HELPER
# ────────────────────────────────────────────────────────────

def _add_keywords_to_adgroup(
    access_token: str,
    cid: str,
    adgroup_id: str,
    keywords: list[str],
):
    """Add broad-match keywords to an existing Google Ad Group."""
    url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroupCriteria:mutate"
    operations = [
        {
            "create": {
                "adGroup": f"customers/{cid}/adGroups/{adgroup_id}",
                "status": "ENABLED",
                "keyword": {
                    "text": kw,
                    "matchType": "BROAD",
                },
            }
        }
        for kw in keywords[:20]  # Google allows up to 20 per request
    ]
    if not operations:
        return
    try:
        _google_post(access_token, url, {"operations": operations})
        logger.info("Added %d keywords to ad group %s", len(operations), adgroup_id)
    except Exception as exc:
        logger.warning("Failed to add keywords to ad group %s: %s", adgroup_id, exc)


# ────────────────────────────────────────────────────────────
# HEADLINE / DESCRIPTION SPLITTERS
# ────────────────────────────────────────────────────────────

def _split_headlines(text: str) -> list[str]:
    """
    Split a headline string into ≤3 parts, each ≤30 characters.
    Google RSA requires 3–15 headlines; we always send exactly 3.
    """
    if not text:
        return ["Visit Our Website", "Learn More Today", "Get Started Now"]

    parts = [p.strip() for p in text.split("|") if p.strip()]
    if not parts:
        parts = [text[:30]]

    result = []
    for p in parts:
        result.append(p[:30])
    while len(result) < 3:
        result.append(result[-1] if result else "Learn More")
    return result[:3]


def _split_descriptions(text: str) -> list[str]:
    """
    Split a description into ≤2 parts, each ≤90 characters.
    Google RSA requires 2–4 descriptions; we always send exactly 2.
    """
    if not text:
        return ["Discover our products and services today.", "Contact us to learn more."]

    parts = [p.strip() for p in text.split("|") if p.strip()]
    if not parts:
        # Auto-split at 90-char boundary
        parts = [text[i:i + 90] for i in range(0, min(len(text), 180), 90)]

    result = [p[:90] for p in parts]
    while len(result) < 2:
        result.append(result[-1] if result else "Contact us today.")
    return result[:2]


# ════════════════════════════════════════════════════════════
#  2 ·  UPDATE CAMPAIGN ON GOOGLE
# ════════════════════════════════════════════════════════════

def update_campaign_on_google(
    unified_campaign_id: int,
    ad_asset: AdAsset | None = None,
):
    """
    Push local changes to the existing Google Campaign / Ad Group / Ad.

    If the campaign has not yet been pushed (no platform_campaign_id),
    falls back to ``create_ad_on_google``.

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign``.
    ad_asset : AdAsset | None
        New asset to associate with local Ad.
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(
        id=unified_campaign_id
    )
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="GOOGLE",
        is_active=True,
    )

    platform_campaign = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
        platform_campaign_id__isnull=False,
    ).first()

    if not platform_campaign:
        return create_ad_on_google(unified_campaign_id, ad_asset)

    cid = _customer_id(integration)
    token = _get_valid_token(integration)
    google_campaign_id = platform_campaign.platform_campaign_id

    # ── Update Campaign ──────────────────────────────────────
    try:
        url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaigns:mutate"
        _google_post(token, url, {
            "operations": [{
                "update": {
                    "resourceName": f"customers/{cid}/campaigns/{google_campaign_id}",
                    "name": campaign.name,
                    "status": _status_to_google(campaign.status),
                },
                "updateMask": "name,status",
            }]
        })
        logger.info("Google Campaign updated: %s", google_campaign_id)
    except Exception as exc:
        logger.error("Failed to update Google Campaign %s: %s", google_campaign_id, exc)
        raise

    # ── Update campaign budget if present ───────────────────
    budget = CampaignBudget.objects.filter(campaign=campaign, platform="GOOGLE").first()
    budget_resource = (platform_campaign.extra_data or {}).get("budget_resource")

    if budget and budget_resource:
        try:
            burl = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaignBudgets:mutate"
            _google_post(token, burl, {
                "operations": [{
                    "update": {
                        "resourceName": budget_resource,
                        "amountMicros": str(_minor_to_micros(budget.daily_budget_minor)),
                    },
                    "updateMask": "amount_micros",
                }]
            })
            logger.info("Google Campaign Budget updated: %s", budget_resource)
        except Exception as exc:
            logger.warning("Failed to update Google budget %s: %s", budget_resource, exc)

    # ── Update Ad Group(s) ───────────────────────────────────
    for ad_group in platform_campaign.ad_groups.all():
        if not ad_group.platform_adgroup_id:
            continue

        try:
            agurl = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroups:mutate"
            _google_post(token, agurl, {
                "operations": [{
                    "update": {
                        "resourceName": (
                            f"customers/{cid}/adGroups/{ad_group.platform_adgroup_id}"
                        ),
                        "name": ad_group.name,
                        "status": _status_to_google(ad_group.status),
                    },
                    "updateMask": "name,status",
                }]
            })
            ad_group.last_synced_at = timezone.now()
            ad_group.error_message = None
            ad_group.save(update_fields=["last_synced_at", "error_message", "updated_at"])
            logger.info("Google Ad Group updated: %s", ad_group.platform_adgroup_id)
        except Exception as exc:
            ad_group.error_message = str(exc)
            ad_group.save(update_fields=["error_message", "updated_at"])
            logger.error("Failed to update Google Ad Group %s: %s", ad_group.platform_adgroup_id, exc)
            raise

        # ── Update Ads ───────────────────────────────────────
        for local_ad in ad_group.ads.all():
            if not local_ad.platform_ad_id:
                continue

            try:
                aurl = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroupAds:mutate"
                _google_post(token, aurl, {
                    "operations": [{
                        "update": {
                            "resourceName": (
                                f"customers/{cid}/adGroupAds/"
                                f"{ad_group.platform_adgroup_id}~{local_ad.platform_ad_id}"
                            ),
                            "status": _status_to_google(local_ad.status),
                        },
                        "updateMask": "status",
                    }]
                })
                logger.info("Google AdGroupAd status updated: %s", local_ad.platform_ad_id)
            except Exception as exc:
                logger.error("Failed to update Google Ad %s: %s", local_ad.platform_ad_id, exc)

            if ad_asset:
                local_ad.assets.add(ad_asset)

    platform_campaign.status = campaign.status
    platform_campaign.last_synced_at = timezone.now()
    platform_campaign.save(update_fields=["status", "last_synced_at", "updated_at"])


# ════════════════════════════════════════════════════════════
#  3 ·  DELETE AD ON GOOGLE
# ════════════════════════════════════════════════════════════

def delete_ad_on_google(
    unified_campaign_id: int,
    delete_level: str = "CAMPAIGN",
) -> list[dict]:
    """
    Remove Google Ads objects tied to a UnifiedCampaign, then clean up locally.

    Parameters
    ----------
    unified_campaign_id : int
        PK of the ``UnifiedCampaign``.
    delete_level : str
        - ``"CAMPAIGN"`` — removes the Google Campaign (cascades ad groups & ads).
        - ``"ADGROUP"``  — removes only ad groups (and their ads).
        - ``"AD"``       — removes only ads, keeps campaign & ad groups.

    Returns
    -------
    list[dict]
        List of error dicts (empty = full success).
    """
    campaign = UnifiedCampaign.objects.select_related("organization").get(
        id=unified_campaign_id
    )
    integration = AdIntegration.objects.get(
        organization=campaign.organization,
        platform="GOOGLE",
        is_active=True,
    )

    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    platform_campaigns = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
    )

    errors: list[dict] = []

    for pc in platform_campaigns:
        if delete_level == "CAMPAIGN":
            _delete_google_campaign(token, cid, pc, errors)
        elif delete_level == "ADGROUP":
            _delete_google_adgroups(token, cid, pc, errors)
        elif delete_level == "AD":
            _delete_google_ads(token, cid, pc, errors)

    if errors:
        logger.warning(
            "Google delete for campaign %s completed with %d error(s): %s",
            unified_campaign_id, len(errors), errors,
        )

    # ── Local cleanup ────────────────────────────────────────
    with transaction.atomic():
        if delete_level == "CAMPAIGN":
            for pc in platform_campaigns:
                pc.ad_groups.all().delete()
            platform_campaigns.delete()
            CampaignBudget.objects.filter(campaign=campaign, platform="GOOGLE").delete()
            campaign.status = "ARCHIVED"
            campaign.save(update_fields=["status", "updated_at"])

        elif delete_level == "ADGROUP":
            for pc in platform_campaigns:
                pc.ad_groups.all().delete()

        elif delete_level == "AD":
            for pc in platform_campaigns:
                for ag in pc.ad_groups.all():
                    ag.ads.all().delete()

    return errors


def _delete_google_campaign(token: str, cid: str, pc: PlatformCampaign, errors: list):
    """Set a Google Campaign status to REMOVED (Google's way of deleting)."""
    if not pc.platform_campaign_id:
        return
    try:
        url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaigns:mutate"
        _google_post(token, url, {
            "operations": [{
                "remove": f"customers/{cid}/campaigns/{pc.platform_campaign_id}",
            }]
        })
        logger.info("Google Campaign removed: %s", pc.platform_campaign_id)
    except Exception as exc:
        logger.error("Failed to remove Google Campaign %s: %s", pc.platform_campaign_id, exc)
        errors.append({"stage": "CAMPAIGN", "id": pc.platform_campaign_id, "error": str(exc)})


def _delete_google_adgroups(token: str, cid: str, pc: PlatformCampaign, errors: list):
    """Remove all Google Ad Groups under a PlatformCampaign."""
    for ag in pc.ad_groups.all():
        if not ag.platform_adgroup_id:
            continue
        _delete_google_ads_in_adgroup(token, cid, ag, errors)
        try:
            url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroups:mutate"
            _google_post(token, url, {
                "operations": [{
                    "remove": f"customers/{cid}/adGroups/{ag.platform_adgroup_id}",
                }]
            })
            logger.info("Google Ad Group removed: %s", ag.platform_adgroup_id)
        except Exception as exc:
            logger.error("Failed to remove Google Ad Group %s: %s", ag.platform_adgroup_id, exc)
            errors.append({"stage": "ADGROUP", "id": ag.platform_adgroup_id, "error": str(exc)})


def _delete_google_ads(token: str, cid: str, pc: PlatformCampaign, errors: list):
    """Remove all Google Ads under all Ad Groups of a PlatformCampaign."""
    for ag in pc.ad_groups.all():
        _delete_google_ads_in_adgroup(token, cid, ag, errors)


def _delete_google_ads_in_adgroup(token: str, cid: str, ag: AdGroup, errors: list):
    """Remove all Google Ads inside a single AdGroup via adGroupAds:mutate."""
    for ad in ag.ads.all():
        if not ad.platform_ad_id or not ag.platform_adgroup_id:
            continue
        try:
            url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroupAds:mutate"
            _google_post(token, url, {
                "operations": [{
                    "remove": (
                        f"customers/{cid}/adGroupAds/"
                        f"{ag.platform_adgroup_id}~{ad.platform_ad_id}"
                    ),
                }]
            })
            logger.info("Google AdGroupAd removed: %s~%s", ag.platform_adgroup_id, ad.platform_ad_id)
        except Exception as exc:
            logger.error("Failed to remove Google Ad %s: %s", ad.platform_ad_id, exc)
            errors.append({"stage": "AD", "id": ad.platform_ad_id, "error": str(exc)})


# ════════════════════════════════════════════════════════════
#  4 ·  TOGGLE CAMPAIGN STATUS (PAUSE / RESUME)
# ════════════════════════════════════════════════════════════

def toggle_campaign_status_on_google(
    unified_campaign_id: int,
    target_status: str,
) -> list[dict]:
    """
    Set all Google Ads objects belonging to *unified_campaign_id* to
    *target_status* (``"ACTIVE"`` or ``"PAUSED"``).

    Updates PlatformCampaign, AdGroup, and Ad rows in the DB to match.
    Returns a list of error dicts (empty = full success).
    """
    from apps.main.models import UnifiedCampaign, PlatformCampaign

    if target_status not in ("ACTIVE", "PAUSED"):
        raise ValueError(f"target_status must be ACTIVE or PAUSED, got {target_status!r}")

    google_status = _status_to_google(target_status)
    errors: list[dict] = []

    campaign = UnifiedCampaign.objects.get(id=unified_campaign_id)

    platform_campaigns = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration__platform="GOOGLE",
    ).select_related("integration").prefetch_related("ad_groups__ads")

    for pc in platform_campaigns:
        integration = pc.integration
        cid = _customer_id(integration)
        try:
            token = _get_valid_token(integration)
        except Exception as exc:
            errors.append({"stage": "AUTH", "error": str(exc)})
            continue

        # ── Campaign level ──────────────────────────────────
        if pc.platform_campaign_id:
            try:
                url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaigns:mutate"
                _google_post(token, url, {
                    "operations": [{
                        "update": {
                            "resourceName": f"customers/{cid}/campaigns/{pc.platform_campaign_id}",
                            "status": google_status,
                        },
                        "updateMask": "status",
                    }]
                })
                pc.status = target_status
                pc.save(update_fields=["status"])
                logger.info("Google Campaign %s set to %s", pc.platform_campaign_id, google_status)
            except Exception as exc:
                logger.error("Failed to update Google Campaign %s: %s", pc.platform_campaign_id, exc)
                errors.append({"stage": "CAMPAIGN", "id": pc.platform_campaign_id, "error": str(exc)})

        # ── Ad Group level ──────────────────────────────────
        for ag in pc.ad_groups.all():
            if ag.platform_adgroup_id:
                try:
                    url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroups:mutate"
                    _google_post(token, url, {
                        "operations": [{
                            "update": {
                                "resourceName": f"customers/{cid}/adGroups/{ag.platform_adgroup_id}",
                                "status": google_status,
                            },
                            "updateMask": "status",
                        }]
                    })
                    ag.status = target_status
                    ag.save(update_fields=["status"])
                    logger.info("Google Ad Group %s set to %s", ag.platform_adgroup_id, google_status)
                except Exception as exc:
                    logger.error("Failed to update Google Ad Group %s: %s", ag.platform_adgroup_id, exc)
                    errors.append({"stage": "ADGROUP", "id": ag.platform_adgroup_id, "error": str(exc)})

            # ── Ad level ─────────────────────────────────────
            for ad in ag.ads.all():
                if ad.platform_ad_id and ag.platform_adgroup_id:
                    try:
                        url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/adGroupAds:mutate"
                        _google_post(token, url, {
                            "operations": [{
                                "update": {
                                    "resourceName": (
                                        f"customers/{cid}/adGroupAds/"
                                        f"{ag.platform_adgroup_id}~{ad.platform_ad_id}"
                                    ),
                                    "status": google_status,
                                },
                                "updateMask": "status",
                            }]
                        })
                        ad.status = target_status
                        ad.save(update_fields=["status"])
                        logger.info("Google Ad %s set to %s", ad.platform_ad_id, google_status)
                    except Exception as exc:
                        logger.error("Failed to update Google Ad %s: %s", ad.platform_ad_id, exc)
                        errors.append({"stage": "AD", "id": ad.platform_ad_id, "error": str(exc)})

    return errors


# ────────────────────────────────────────────────────────────
# PRIVATE: _google_post with token (helper alias for clarity)
# ────────────────────────────────────────────────────────────

def _google_post(access_token: str, url: str, payload: dict, login_customer_id: str | None = None) -> dict:  # noqa: F811
    """POST to the Google Ads REST API, raise on non-2xx or API error."""
    resp = requests.post(
        url,
        headers=_headers(access_token, login_customer_id),
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Google Ads API POST {url} failed [{resp.status_code}]: {resp.text}"
        )
    data = resp.json()
    # Google returns a top-level "partialFailureError" for batch errors
    if "partialFailureError" in data:
        raise RuntimeError(
            f"Google Ads API partial failure: {data['partialFailureError']}"
        )
    return data


# ────────────────────────────────────────────────────────────
# DELETE CAMPAIGN BY PLATFORM CAMPAIGN (used by Celery delete task)
# ────────────────────────────────────────────────────────────

def delete_campaign_on_google(platform_campaign_id: str, integration) -> list[dict]:
    """
    Remove a Google Campaign by its platform-level resource ID.

    Called by the background delete task *after* the local UnifiedCampaign
    row has already been removed from the DB.

    Returns a list of error dicts (empty = success).
    """
    cid = _customer_id(integration)
    token = _get_valid_token(integration)
    errors: list[dict] = []
    try:
        url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/campaigns:mutate"
        _google_post(token, url, {
            "operations": [{
                "remove": f"customers/{cid}/campaigns/{platform_campaign_id}",
            }]
        })
        logger.info("Google Campaign removed (by task): %s", platform_campaign_id)
    except Exception as exc:
        logger.error("Failed to remove Google Campaign %s: %s", platform_campaign_id, exc)
        errors.append({"stage": "CAMPAIGN", "id": platform_campaign_id, "error": str(exc)})
    return errors
