"""
Google Ads Sync Engine — Campaigns, Ad Groups, Ads

Mirrors the Meta / TikTok sync engine architecture:
  1. Fetch campaigns from Google Ads (via GAQL search)
  2. Upsert into UnifiedCampaign + PlatformCampaign
  3. Fetch ad groups → AdGroup
  4. Fetch ads → Ad

All API calls use Google Ads REST API v18 (googleads.googleapis.com).
Authentication: OAuth2 Bearer token stored in AdIntegration.access_token,
refreshed automatically via refresh_token if expired.

Google Ads Query Language (GAQL) reference:
  https://developers.google.com/google-ads/api/docs/query/overview
"""

import logging
from datetime import timedelta
from datetime import date as date_type

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from main.models import (
    UnifiedCampaign,
    PlatformCampaign,
    CampaignBudget,
    AdGroup,
    Ad,
    IntegrationSyncState,
)
from finance.utils import increment_campaign_usage

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_VERSION = "v18"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"


# ============================================================
# HTTP / AUTH HELPERS
# ============================================================

def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "Content-Type": "application/json",
    }


def _customer_id(integration) -> str:
    """Return the customer ID stripped of dashes."""
    return str(integration.ad_account_id).replace("-", "")


def _refresh_access_token(integration) -> str:
    """
    Use the stored refresh_token to obtain a new access_token.
    Updates the integration in-place and in the DB.
    """
    if not integration.refresh_token:
        raise RuntimeError(
            "No refresh_token stored. Re-connect the Google integration."
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
        raise RuntimeError(f"Google token refresh failed: {data}")

    new_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    integration.access_token = new_token
    integration.token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    integration.save(update_fields=["access_token", "token_expires_at"])
    logger.info("Google access token refreshed for integration %s", integration.id)
    return new_token


def _get_valid_token(integration) -> str:
    """Return a valid access token, refreshing if expired or close to expiry."""
    if integration.token_expires_at and timezone.now() >= (
        integration.token_expires_at - timedelta(minutes=5)
    ):
        return _refresh_access_token(integration)
    return integration.access_token


def _google_search(cid: str, access_token: str, query: str) -> list[dict]:
    """
    Execute a GAQL search query, handling pagination via nextPageToken.
    Returns a flat list of result rows.
    """
    url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/googleAds:search"
    all_rows = []
    page_token = None

    while True:
        payload = {"query": query, "pageSize": 1000}
        if page_token:
            payload["pageToken"] = page_token

        resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
        if not resp.ok:
            raise RuntimeError(
                f"Google Ads search failed [{resp.status_code}]: {resp.text}"
            )

        data = resp.json()
        rows = data.get("results", [])
        all_rows.extend(rows)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return all_rows


# ============================================================
# OBJECTIVE / STATUS MAPPINGS
# ============================================================

GOOGLE_CAMPAIGN_TYPE_TO_UNIFIED = {
    "SEARCH": "TRAFFIC",
    "DISPLAY": "AWARENESS",
    "SHOPPING": "CONVERSIONS",
    "VIDEO": "AWARENESS",
    "APP": "APP_PROMOTION",
    "SMART": "TRAFFIC",
    "PERFORMANCE_MAX": "CONVERSIONS",
    "DISCOVERY": "ENGAGEMENT",
    "LOCAL": "ENGAGEMENT",
    "HOTEL": "CONVERSIONS",
    "LOCAL_SERVICES": "LEADS",
}

GOOGLE_STATUS_TO_UNIFIED = {
    "ENABLED": "ACTIVE",
    "PAUSED": "PAUSED",
    "REMOVED": "ARCHIVED",
}


def _map_google_objective(advertising_channel_type: str) -> str:
    return GOOGLE_CAMPAIGN_TYPE_TO_UNIFIED.get(advertising_channel_type, "TRAFFIC")


def _map_google_status(google_status: str) -> str:
    return GOOGLE_STATUS_TO_UNIFIED.get(google_status, "PAUSED")


# ============================================================
# STAGE 1: FETCH CAMPAIGNS
# ============================================================

def fetch_google_campaigns(integration) -> list[dict]:
    """
    Fetch all non-removed campaigns from Google Ads for the given integration.

    Returns a list of dicts with keys:
      id, name, status, advertising_channel_type,
      budget_amount_micros, budget_type, start_date, end_date
    """
    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    query = """
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign.advertising_channel_type,
            campaign.start_date,
            campaign.end_date,
            campaign_budget.amount_micros,
            campaign_budget.type
        FROM campaign
        WHERE campaign.status != 'REMOVED'
        ORDER BY campaign.id
    """

    rows = _google_search(cid, token, query)

    campaigns = []
    for row in rows:
        c = row.get("campaign", {})
        b = row.get("campaignBudget", {})
        campaigns.append({
            "id": str(c.get("id", "")),
            "name": c.get("name", ""),
            "status": c.get("status", "PAUSED"),
            "advertising_channel_type": c.get("advertisingChannelType", "SEARCH"),
            "start_date": c.get("startDate"),
            "end_date": c.get("endDate"),
            "budget_amount_micros": b.get("amountMicros", 0),
            "budget_type": b.get("type", "STANDARD"),
        })

    logger.info("Fetched %d Google campaigns for %s", len(campaigns), integration)
    return campaigns


# ============================================================
# STAGE 2: UPSERT CAMPAIGNS
# ============================================================

@transaction.atomic
def upsert_google_campaigns(google_campaigns: list[dict], integration) -> list:
    """
    Upsert Google campaigns into UnifiedCampaign + PlatformCampaign.
    Mirrors upsert_campaigns (meta) and upsert_tiktok_campaigns.
    """
    platform_campaigns = []

    for gc in google_campaigns:
        campaign_id = gc["id"]
        campaign_name = gc["name"]
        objective = _map_google_objective(gc["advertising_channel_type"])
        status = _map_google_status(gc["status"])

        platform_campaign = PlatformCampaign.objects.filter(
            integration=integration,
            platform_campaign_id=campaign_id,
        ).select_related("unified_campaign").first()

        if not platform_campaign:
            unified = UnifiedCampaign.objects.create(
                organization=integration.organization,
                name=campaign_name,
                objective=objective,
                status=status,
                currency="USD",
            )
            platform_campaign = PlatformCampaign.objects.create(
                integration=integration,
                platform_campaign_id=campaign_id,
                unified_campaign=unified,
                status=status,
                extra_data=gc,
                last_synced_at=timezone.now(),
            )
            increment_campaign_usage(integration.organization)

        else:
            if not platform_campaign.unified_campaign:
                unified = UnifiedCampaign.objects.create(
                    organization=integration.organization,
                    name=campaign_name,
                    objective=objective,
                    status=status,
                    currency="USD",
                )
                platform_campaign.unified_campaign = unified
                increment_campaign_usage(integration.organization)
            else:
                unified = platform_campaign.unified_campaign
                unified.name = campaign_name
                unified.status = status
                unified.objective = objective
                unified.save()

            platform_campaign.status = status
            platform_campaign.extra_data = gc
            platform_campaign.last_synced_at = timezone.now()
            platform_campaign.save()

        # Budget — convert micros to cents (minor units)
        _upsert_budget_from_google(
            unified_campaign=platform_campaign.unified_campaign,
            budget_amount_micros=gc.get("budget_amount_micros", 0),
            budget_type_raw=gc.get("budget_type", "STANDARD"),
            start_date=gc.get("start_date"),
            end_date=gc.get("end_date"),
            source="campaign",
        )

        platform_campaigns.append(platform_campaign)

    return platform_campaigns


def _upsert_budget_from_google(
    unified_campaign,
    budget_amount_micros,
    budget_type_raw: str,
    start_date,
    end_date,
    source: str = "campaign",
):
    """
    Create / update a CampaignBudget from Google budget fields.

    Google stores budgets in *micros* (1/1,000,000 of the currency unit).
    We store in *minor units* (cents = 1/100), so:
        cents = micros // 10_000
    """
    micros = int(budget_amount_micros or 0)
    if micros <= 0:
        logger.debug(
            "Skipping budget upsert for %s (GOOGLE) — no budget micros from %s.",
            unified_campaign, source,
        )
        return

    minor = micros // 10_000  # convert micros → cents

    # Google budget types: STANDARD (daily) or FIXED (lifetime)
    budget_type = "LIFETIME" if "FIXED" in str(budget_type_raw).upper() else "DAILY"

    defaults = {
        "budget_type": budget_type,
        "daily_budget_minor": minor,
        "run_continuously": not end_date,
    }

    if start_date:
        defaults["start_date"] = start_date
    if end_date:
        defaults["end_date"] = end_date

    obj, created = CampaignBudget.objects.update_or_create(
        campaign=unified_campaign,
        platform="GOOGLE",
        defaults=defaults,
    )
    logger.info(
        "Budget %s for campaign %s [GOOGLE] from %s: %s %d minor-units",
        "created" if created else "updated",
        unified_campaign, source, budget_type, minor,
    )


# ============================================================
# STAGE 3: SYNC AD GROUPS
# ============================================================

def sync_google_adgroups(platform_campaigns: list, integration) -> list:
    """
    Fetch and upsert Google Ad Groups for the given platform campaigns.
    Uses GAQL to query ad_group filtered by campaign resource names.
    """
    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    campaign_ids = [
        pc.platform_campaign_id
        for pc in platform_campaigns
        if pc.platform_campaign_id
    ]
    if not campaign_ids:
        return []

    # Build comma-separated id list for the IN clause
    ids_str = ", ".join(campaign_ids)
    query = f"""
        SELECT
            ad_group.id,
            ad_group.name,
            ad_group.status,
            ad_group.campaign,
            ad_group.cpc_bid_micros,
            ad_group.type,
            campaign.id
        FROM ad_group
        WHERE campaign.id IN ({ids_str})
          AND ad_group.status != 'REMOVED'
    """

    rows = _google_search(cid, token, query)
    logger.info("Fetched %d Google ad groups", len(rows))

    # Build lookup: campaign_id → PlatformCampaign
    pc_map = {pc.platform_campaign_id: pc for pc in platform_campaigns}
    all_adgroups = []

    for row in rows:
        ag_data = row.get("adGroup", {})
        c_data = row.get("campaign", {})

        adgroup_id = str(ag_data.get("id", ""))
        campaign_id = str(c_data.get("id", ""))
        pc = pc_map.get(campaign_id)
        if not pc or not adgroup_id:
            continue

        status = _map_google_status(ag_data.get("status", "PAUSED"))

        ad_group, _ = AdGroup.objects.update_or_create(
            platform_campaign=pc,
            platform_adgroup_id=adgroup_id,
            defaults={
                "name": ag_data.get("name", ""),
                "status": status,
                "targeting_config": {
                    "type": ag_data.get("type", "SEARCH_STANDARD"),
                    "cpc_bid_micros": ag_data.get("cpcBidMicros", 0),
                },
                "last_synced_at": timezone.now(),
            },
        )
        all_adgroups.append(ad_group)

    return all_adgroups


# ============================================================
# STAGE 4: SYNC ADS
# ============================================================

def sync_google_ads(ad_groups: list, integration) -> None:
    """
    Fetch and upsert Google Ads for the given ad groups.
    Queries ad_group_ad via GAQL filtered by ad group IDs.
    """
    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    adgroup_ids = [ag.platform_adgroup_id for ag in ad_groups if ag.platform_adgroup_id]
    if not adgroup_ids:
        return

    ag_map = {ag.platform_adgroup_id: ag for ag in ad_groups}

    ids_str = ", ".join(adgroup_ids)
    query = f"""
        SELECT
            ad_group_ad.ad.id,
            ad_group_ad.ad.name,
            ad_group_ad.status,
            ad_group_ad.ad.final_urls,
            ad_group_ad.ad.responsive_search_ad.headlines,
            ad_group_ad.ad.responsive_search_ad.descriptions,
            ad_group_ad.ad.type,
            ad_group.id
        FROM ad_group_ad
        WHERE ad_group.id IN ({ids_str})
          AND ad_group_ad.status != 'REMOVED'
    """

    rows = _google_search(cid, token, query)
    logger.info("Fetched %d Google ads", len(rows))

    for row in rows:
        aga = row.get("adGroupAd", {})
        ag_data = row.get("adGroup", {})
        ad_data = aga.get("ad", {})

        ad_id = str(ad_data.get("id", ""))
        adgroup_id = str(ag_data.get("id", ""))
        ag = ag_map.get(adgroup_id)
        if not ag or not ad_id:
            continue

        status = _map_google_status(aga.get("status", "PAUSED"))

        # Extract headline / description from RSA or name fallback
        rsa = ad_data.get("responsiveSearchAd", {})
        headlines = rsa.get("headlines", [])
        descriptions = rsa.get("descriptions", [])

        headline_text = " | ".join(
            h.get("text", "") for h in headlines if h.get("text")
        )[:255]
        description_text = " | ".join(
            d.get("text", "") for d in descriptions if d.get("text")
        )[:255]

        final_urls = ad_data.get("finalUrls", [])
        destination_url = final_urls[0] if final_urls else ""

        Ad.objects.update_or_create(
            ad_group=ag,
            platform_ad_id=ad_id,
            defaults={
                "name": ad_data.get("name", f"Google Ad {ad_id}"),
                "status": status,
                "headline": headline_text,
                "description": description_text,
                "destination_url": destination_url,
            },
        )


# ============================================================
# ORCHESTRATOR (RESUMABLE)
# ============================================================

SYNC_STAGES = [
    "FETCH_CAMPAIGNS",
    "UPSERT_CAMPAIGNS",
    "SYNC_ADGROUPS",
    "SYNC_ADS",
]


def sync_google_integration(integration):
    """
    Full 4-stage sync for a Google Ads integration.

    Mirrors ``sync_meta_integration`` and ``sync_tiktok_integration`` —
    uses ``IntegrationSyncState`` for resumability and error tracking.
    """
    state, _ = IntegrationSyncState.objects.get_or_create(integration=integration)

    google_campaigns = []
    platform_campaigns = []
    ad_groups = []

    for stage in SYNC_STAGES:
        try:
            if stage == "FETCH_CAMPAIGNS":
                google_campaigns = fetch_google_campaigns(integration)

            elif stage == "UPSERT_CAMPAIGNS":
                if not google_campaigns:
                    google_campaigns = fetch_google_campaigns(integration)
                platform_campaigns = upsert_google_campaigns(google_campaigns, integration)

            elif stage == "SYNC_ADGROUPS":
                if not platform_campaigns:
                    platform_campaigns = list(PlatformCampaign.objects.filter(
                        integration=integration,
                        platform_campaign_id__isnull=False,
                    ))
                ad_groups = sync_google_adgroups(platform_campaigns, integration)

            elif stage == "SYNC_ADS":
                if not ad_groups:
                    ad_groups = list(AdGroup.objects.filter(
                        platform_campaign__integration=integration,
                        platform_adgroup_id__isnull=False,
                    ))
                sync_google_ads(ad_groups, integration)

            state.last_successful_stage = stage
            state.last_error_stage = None
            state.error_message = None
            state.save()

        except Exception as e:
            state.last_error_stage = stage
            state.error_message = str(e)
            state.save()
            logger.error("Google sync failed at stage %s: %s", stage, e)
            raise
