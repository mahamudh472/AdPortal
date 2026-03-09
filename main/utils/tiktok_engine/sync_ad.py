"""
TikTok Ads Sync Engine — Campaigns, Ad Groups, Ads

Mirrors the Meta sync engine architecture:
  1. Fetch campaigns from TikTok
  2. Upsert into UnifiedCampaign + PlatformCampaign
  3. Fetch ad groups → AdGroup
  4. Fetch ads → Ad

All API calls use TikTok Marketing API v1.3.
Docs: https://business-api.tiktok.com/marketing_api/docs
"""

import logging
import json
from datetime import date

import requests
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

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


# ============================================================
# HELPERS
# ============================================================

def _headers(access_token: str) -> dict:
    return {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }


def _tiktok_get(endpoint: str, access_token: str, params: dict) -> dict:
    """Make a GET request to TikTok API and return the JSON response."""
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"TikTok API error on {endpoint}: [{data.get('code')}] {data.get('message')}"
        )
    return data.get("data", {})


def _map_tiktok_objective(objective_type: str) -> str:
    """Map TikTok objective_type to our unified objective."""
    mapping = {
        "TRAFFIC": "TRAFFIC",
        "CONVERSIONS": "CONVERSIONS",
        "REACH": "AWARENESS",
        "VIDEO_VIEWS": "AWARENESS",
        "APP_PROMOTION": "APP_PROMOTION",
        "LEAD_GENERATION": "LEAD_GENERATION",
        "WEB_CONVERSIONS": "CONVERSIONS",
        "CATALOG_SALES": "CONVERSIONS",
        "ENGAGEMENT": "ENGAGEMENT",
        "COMMUNITY_INTERACTION": "ENGAGEMENT",
        "APP_INSTALL": "APP_PROMOTION",
        "PRODUCT_SALES": "CONVERSIONS",
        "WEBSITE_CONVERSIONS": "CONVERSIONS",
    }
    return mapping.get(objective_type, "")


def _map_tiktok_status(status_info: dict | str) -> str:
    """Map TikTok status to our unified status.

    TikTok returns status in various ways depending on the endpoint:
    - ``primary_status``: the effective status (e.g., STATUS_ENABLE)
    - ``operation_status``: what the user set
    - ``secondary_status``: detailed reason
    """
    if isinstance(status_info, dict):
        primary = status_info.get("primary_status", "")
        operation = status_info.get("operation_status", "")
        raw = primary or operation
    else:
        raw = str(status_info)

    raw = raw.upper()

    if raw in ("ENABLE", "STATUS_ENABLE", "CAMPAIGN_STATUS_ENABLE",
               "ADGROUP_STATUS_DELIVERY_OK", "AD_STATUS_DELIVERY_OK",
               "STATUS_DELIVERY_OK"):
        return "ACTIVE"
    elif raw in ("DISABLE", "STATUS_DISABLE", "CAMPAIGN_STATUS_DISABLE",
                 "ADGROUP_STATUS_DISABLE", "AD_STATUS_DISABLE",
                 "STATUS_NOT_DELIVERY"):
        return "PAUSED"
    elif raw in ("DELETE", "STATUS_DELETE", "CAMPAIGN_STATUS_DELETE",
                 "ADGROUP_STATUS_DELETE", "AD_STATUS_DELETE"):
        return "ARCHIVED"
    else:
        return "PAUSED"


# ============================================================
# STAGE 1: FETCH CAMPAIGNS
# ============================================================

def fetch_tiktok_campaigns(integration) -> list[dict]:
    """Fetch all campaigns from TikTok for the given integration."""
    all_campaigns = []
    page = 1
    page_size = 100

    while True:
        data = _tiktok_get(
            "campaign/get/",
            access_token=integration.access_token,
            params={
                "advertiser_id": integration.ad_account_id,
                "page": page,
                "page_size": page_size,
            },
        )
        campaigns = data.get("list", [])
        all_campaigns.extend(campaigns)

        total = data.get("page_info", {}).get("total_number", 0)
        if len(all_campaigns) >= total or not campaigns:
            break
        page += 1

    logger.info("Fetched %d TikTok campaigns for %s", len(all_campaigns), integration)
    return all_campaigns


# ============================================================
# STAGE 2: UPSERT CAMPAIGNS
# ============================================================

@transaction.atomic
def upsert_tiktok_campaigns(tiktok_campaigns: list[dict], integration) -> list:
    """Upsert TikTok campaigns into UnifiedCampaign + PlatformCampaign."""
    platform_campaigns = []

    for tc in tiktok_campaigns:
        campaign_id = str(tc.get("campaign_id"))
        campaign_name = tc.get("campaign_name", "")
        objective = _map_tiktok_objective(tc.get("objective_type", ""))
        status = _map_tiktok_status(tc)

        platform_campaign = PlatformCampaign.objects.filter(
            integration=integration,
            platform_campaign_id=campaign_id,
        ).select_related("unified_campaign").first()

        if not platform_campaign:
            # Create new unified + platform campaign
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
                extra_data=tc,
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
            platform_campaign.extra_data = tc
            platform_campaign.last_synced_at = timezone.now()
            platform_campaign.save()

        # Budget
        _upsert_budget_from_tiktok(
            unified_campaign=platform_campaign.unified_campaign,
            budget_mode=tc.get("budget_mode"),
            budget=tc.get("budget"),
            source="campaign",
        )

        platform_campaigns.append(platform_campaign)

    return platform_campaigns


def _upsert_budget_from_tiktok(
    unified_campaign,
    budget_mode: str | None,
    budget: float | None,
    source: str = "campaign",
):
    """Create/update CampaignBudget from TikTok budget fields.

    TikTok budget is already in currency units (not minor/cents).
    We store in minor units (cents) for consistency with Meta.
    """
    if not budget or float(budget) <= 0:
        return

    budget_val = float(budget)
    # Convert to minor units (cents)
    budget_minor = int(round(budget_val * 100))

    budget_type = "DAILY"
    if budget_mode and "TOTAL" in str(budget_mode).upper():
        budget_type = "LIFETIME"

    defaults = {
        "budget_type": budget_type,
        "daily_budget_minor": budget_minor,
    }

    obj, created = CampaignBudget.objects.update_or_create(
        campaign=unified_campaign,
        platform="TIKTOK",
        defaults=defaults,
    )
    logger.info(
        "Budget %s for campaign %s [TIKTOK] from %s: %s %d",
        "created" if created else "updated",
        unified_campaign, source, budget_type, budget_minor,
    )


# ============================================================
# STAGE 3: SYNC AD GROUPS
# ============================================================

def sync_tiktok_adgroups(platform_campaigns: list, integration) -> list:
    """Fetch and upsert TikTok ad groups for the given platform campaigns."""
    all_adgroups = []

    campaign_ids = [pc.platform_campaign_id for pc in platform_campaigns if pc.platform_campaign_id]
    if not campaign_ids:
        return all_adgroups

    # Fetch all ad groups in batches (TikTok supports filtering by campaign_ids)
    page = 1
    page_size = 100
    tiktok_adgroups = []

    while True:
        data = _tiktok_get(
            "adgroup/get/",
            access_token=integration.access_token,
            params={
                "advertiser_id": integration.ad_account_id,
                "campaign_ids": json.dumps(campaign_ids),
                "page": page,
                "page_size": page_size,
            },
        )
        items = data.get("list", [])
        tiktok_adgroups.extend(items)

        total = data.get("page_info", {}).get("total_number", 0)
        if len(tiktok_adgroups) >= total or not items:
            break
        page += 1

    logger.info("Fetched %d TikTok ad groups", len(tiktok_adgroups))

    # Build lookup: campaign_id → PlatformCampaign
    pc_map = {pc.platform_campaign_id: pc for pc in platform_campaigns}

    for ag in tiktok_adgroups:
        adgroup_id = str(ag.get("adgroup_id"))
        campaign_id = str(ag.get("campaign_id"))
        pc = pc_map.get(campaign_id)
        if not pc:
            continue

        targeting = {}
        # Gather targeting fields from TikTok response
        for key in ("location_ids", "gender", "age_groups", "languages",
                     "interest_category_ids", "interest_keyword_ids",
                     "audience_ids", "excluded_audience_ids",
                     "operating_systems", "device_model_ids"):
            if ag.get(key):
                targeting[key] = ag[key]

        status = _map_tiktok_status(ag)

        ad_group, _ = AdGroup.objects.update_or_create(
            platform_campaign=pc,
            platform_adgroup_id=adgroup_id,
            defaults={
                "name": ag.get("adgroup_name", ""),
                "status": status,
                "daily_budget": ag.get("budget"),
                "targeting_config": targeting,
                "start_time": ag.get("schedule_start_time"),
                "end_time": ag.get("schedule_end_time"),
                "last_synced_at": timezone.now(),
            },
        )

        # Ad-group level budget (if campaign has no budget)
        has_campaign_budget = CampaignBudget.objects.filter(
            campaign=pc.unified_campaign,
            platform="TIKTOK",
        ).exists()

        if not has_campaign_budget:
            _upsert_budget_from_tiktok(
                unified_campaign=pc.unified_campaign,
                budget_mode=ag.get("budget_mode"),
                budget=ag.get("budget"),
                source="adgroup",
            )

        all_adgroups.append(ad_group)

    return all_adgroups


# ============================================================
# STAGE 4: SYNC ADS
# ============================================================

def sync_tiktok_ads(ad_groups: list, integration) -> None:
    """Fetch and upsert TikTok ads for the given ad groups."""
    adgroup_ids = [ag.platform_adgroup_id for ag in ad_groups if ag.platform_adgroup_id]
    if not adgroup_ids:
        return

    # Build lookup: adgroup_id → AdGroup
    ag_map = {ag.platform_adgroup_id: ag for ag in ad_groups}

    page = 1
    page_size = 100
    tiktok_ads = []

    while True:
        data = _tiktok_get(
            "ad/get/",
            access_token=integration.access_token,
            params={
                "advertiser_id": integration.ad_account_id,
                "adgroup_ids": json.dumps(adgroup_ids),
                "page": page,
                "page_size": page_size,
            },
        )
        items = data.get("list", [])
        tiktok_ads.extend(items)

        total = data.get("page_info", {}).get("total_number", 0)
        if len(tiktok_ads) >= total or not items:
            break
        page += 1

    logger.info("Fetched %d TikTok ads", len(tiktok_ads))

    for ad in tiktok_ads:
        ad_id = str(ad.get("ad_id"))
        adgroup_id = str(ad.get("adgroup_id"))
        ag = ag_map.get(adgroup_id)
        if not ag:
            continue

        status = _map_tiktok_status(ad)

        # Extract creative info
        headline = ad.get("ad_text", "") or ad.get("ad_name", "")
        destination_url = ad.get("landing_page_url", "")
        call_to_action = ad.get("call_to_action", "")
        display_name = ad.get("display_name", "")

        Ad.objects.update_or_create(
            ad_group=ag,
            platform_ad_id=ad_id,
            defaults={
                "name": ad.get("ad_name", ""),
                "status": status,
                "headline": headline,
                "primary_text": ad.get("ad_text", ""),
                "destination_url": destination_url,
                "call_to_action": call_to_action,
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


def sync_tiktok_integration(integration):
    """
    Full 4-stage sync for a TikTok integration.

    Mirrors `sync_meta_integration` — uses `IntegrationSyncState` for
    resumability and error tracking.
    """
    state, _ = IntegrationSyncState.objects.get_or_create(integration=integration)

    tiktok_campaigns = []
    platform_campaigns = []
    ad_groups = []

    for stage in SYNC_STAGES:
        try:
            if stage == "FETCH_CAMPAIGNS":
                tiktok_campaigns = fetch_tiktok_campaigns(integration)

            elif stage == "UPSERT_CAMPAIGNS":
                if not tiktok_campaigns:
                    tiktok_campaigns = fetch_tiktok_campaigns(integration)
                platform_campaigns = upsert_tiktok_campaigns(tiktok_campaigns, integration)

            elif stage == "SYNC_ADGROUPS":
                if not platform_campaigns:
                    platform_campaigns = list(PlatformCampaign.objects.filter(
                        integration=integration,
                        platform_campaign_id__isnull=False,
                    ))
                ad_groups = sync_tiktok_adgroups(platform_campaigns, integration)

            elif stage == "SYNC_ADS":
                if not ad_groups:
                    ad_groups = list(AdGroup.objects.filter(
                        platform_campaign__integration=integration,
                        platform_adgroup_id__isnull=False,
                    ))
                sync_tiktok_ads(ad_groups, integration)

            state.last_successful_stage = stage
            state.last_error_stage = None
            state.error_message = None
            state.save()

        except Exception as e:
            state.last_error_stage = stage
            state.error_message = str(e)
            state.save()
            logger.error("TikTok sync failed at stage %s: %s", stage, e)
            raise

