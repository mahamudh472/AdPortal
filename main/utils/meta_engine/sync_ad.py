import logging
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet

from main.models import (
    UnifiedCampaign,
    PlatformCampaign,
    CampaignBudget,
    AdGroup,
    Ad,
    IntegrationSyncState,
)

logger = logging.getLogger(__name__)


# ============================================================
# SDK INIT
# ============================================================

def init_meta_api(access_token: str):
    FacebookAdsApi.init(
        settings.META_APP_ID,
        settings.META_APP_SECRET,
        access_token,
        api_version="v19.0",
    )


# ============================================================
# HELPERS
# ============================================================

def map_meta_objective(obj):
    mapping = {
        "OUTCOME_SALES": "SALES",
        "OUTCOME_TRAFFIC": "TRAFFIC",
        "OUTCOME_LEADS": "LEADS",
    }
    return mapping.get(obj, "")


# 1: FETCH CAMPAIGNS (READ ONLY)

def fetch_meta_campaigns(integration):

    account = AdAccount(integration.ad_account_id)

    campaigns = account.get_campaigns(fields=[
        "id",
        "name",
        "objective",
        "status",
        "daily_budget",
        "lifetime_budget",
        "start_time",
        "stop_time",
    ])

    return list(campaigns)


# ============================================================
# STAGE 2: UPSERT CAMPAIGNS
# ============================================================


@transaction.atomic
def upsert_campaigns(meta_campaigns, integration):

    platform_campaigns = []

    for meta_campaign in meta_campaigns:

        platform_campaign = PlatformCampaign.objects.filter(
            integration=integration,
            platform_campaign_id=meta_campaign["id"]
        ).select_related("unified_campaign").first()

        # -------------------------------------------------
        # CASE 1: PlatformCampaign DOES NOT exist
        # -------------------------------------------------
        if not platform_campaign:

            unified = UnifiedCampaign.objects.create(
                organization=integration.organization,
                name=meta_campaign["name"],
                objective=map_meta_objective(meta_campaign.get("objective")),
                status=meta_campaign.get("status"),
                currency="USD",
            )

            platform_campaign = PlatformCampaign.objects.create(
                integration=integration,
                platform_campaign_id=meta_campaign["id"],
                unified_campaign=unified,
                status=meta_campaign.get("status"),
                extra_data=meta_campaign.export_all_data(),
                last_synced_at=timezone.now(),
            )

        # -------------------------------------------------
        # CASE 2: PlatformCampaign exists
        # -------------------------------------------------
        else:

            # CASE 2A: unified_campaign missing → create one
            if not platform_campaign.unified_campaign:

                unified = UnifiedCampaign.objects.create(
                    organization=integration.organization,
                    name=meta_campaign["name"],
                    objective=map_meta_objective(meta_campaign.get("objective")),
                    status=meta_campaign.get("status"),
                    currency="USD",
                )

                platform_campaign.unified_campaign = unified

            # CASE 2B: unified exists → update it
            else:
                unified = platform_campaign.unified_campaign
                unified.name = meta_campaign["name"]
                unified.status = meta_campaign.get("status")
                unified.objective = map_meta_objective(
                    meta_campaign.get("objective")
                )
                unified.save()

            # Always update platform fields
            platform_campaign.status = meta_campaign.get("status")
            platform_campaign.extra_data = meta_campaign.export_all_data()
            platform_campaign.last_synced_at = timezone.now()
            platform_campaign.save()

        # -------------------------------------------------
        # Budget — campaign-level (CBO campaigns)
        # -------------------------------------------------
        _upsert_budget_from_meta(
            unified_campaign=platform_campaign.unified_campaign,
            platform=integration.platform,
            daily_budget=meta_campaign.get("daily_budget"),
            lifetime_budget=meta_campaign.get("lifetime_budget"),
            start_time=meta_campaign.get("start_time"),
            stop_time=meta_campaign.get("stop_time"),
            source="campaign",
        )

        platform_campaigns.append(platform_campaign)

    return platform_campaigns


# ============================================================
# BUDGET HELPER
# ============================================================

def _upsert_budget_from_meta(
    unified_campaign,
    platform,
    daily_budget,
    lifetime_budget,
    start_time,
    stop_time,
    source="campaign",
):
    """Create / update a CampaignBudget from Meta budget fields.

    Works for both campaign-level (CBO) and ad-set-level (ABO) budgets.
    Skips silently when neither daily nor lifetime budget is present.
    """
    # Meta returns budget values as strings; filter out None / "0" / empty
    daily_val = int(daily_budget) if daily_budget and str(daily_budget) != "0" else 0
    lifetime_val = int(lifetime_budget) if lifetime_budget and str(lifetime_budget) != "0" else 0

    if not daily_val and not lifetime_val:
        logger.debug(
            "Skipping budget upsert for %s (%s) — no budget value from %s.",
            unified_campaign, platform, source,
        )
        return

    budget_defaults = {
        "start_date": start_time[:10] if start_time else date.today(),
        "run_continuously": not stop_time,
    }

    if stop_time:
        budget_defaults["end_date"] = stop_time[:10]

    if daily_val:
        budget_defaults["budget_type"] = "DAILY"
        budget_defaults["daily_budget_minor"] = daily_val
    else:
        budget_defaults["budget_type"] = "LIFETIME"
        budget_defaults["daily_budget_minor"] = lifetime_val

    obj, created = CampaignBudget.objects.update_or_create(
        campaign=unified_campaign,
        platform=platform,
        defaults=budget_defaults,
    )
    logger.info(
        "Budget %s for campaign %s [%s] from %s: %s %s",
        "created" if created else "updated",
        unified_campaign,
        platform,
        source,
        budget_defaults.get("budget_type"),
        budget_defaults.get("daily_budget_minor"),
    )


# ============================================================
# STAGE 3: SYNC ADSETS
# ============================================================

def sync_adsets(platform_campaigns):

    all_adgroups = []

    for platform_campaign in platform_campaigns:

        unified_campaign = platform_campaign.unified_campaign
        campaign = Campaign(platform_campaign.platform_campaign_id)

        adsets = campaign.get_ad_sets(fields=[
            "id",
            "name",
            "status",
            "daily_budget",
            "lifetime_budget",
            "targeting",
            "start_time",
            "end_time",
        ])

        # Track whether we already have a campaign-level budget
        has_campaign_budget = CampaignBudget.objects.filter(
            campaign=unified_campaign,
            platform=platform_campaign.integration.platform,
        ).exists()

        for adset in adsets:
            targeting = adset.get("targeting")
            targeting_data = (
                targeting.export_all_data() if targeting else {}
            )
            ad_group, _ = AdGroup.objects.update_or_create(
                platform_campaign=platform_campaign,
                platform_adgroup_id=adset["id"],
                defaults={
                    "name": adset["name"],
                    "status": adset["status"],
                    "daily_budget": adset.get("daily_budget"),
                    "targeting_config": targeting_data,
                    "start_time": adset.get("start_time"),
                    "end_time": adset.get("end_time"),
                    "last_synced_at": timezone.now(),
                }
            )

            # If no campaign-level budget exists, use the ad-set budget (ABO)
            if not has_campaign_budget:
                _upsert_budget_from_meta(
                    unified_campaign=unified_campaign,
                    platform=platform_campaign.integration.platform,
                    daily_budget=adset.get("daily_budget"),
                    lifetime_budget=adset.get("lifetime_budget"),
                    start_time=adset.get("start_time"),
                    stop_time=adset.get("end_time"),
                    source="adset",
                )
                # After first successful upsert, mark as having a budget
                # so we don't overwrite with a different adset's budget
                if CampaignBudget.objects.filter(
                    campaign=unified_campaign,
                    platform=platform_campaign.integration.platform,
                ).exists():
                    has_campaign_budget = True

            all_adgroups.append(ad_group)

    return all_adgroups


# ============================================================
# STAGE 4: SYNC ADS
# ============================================================

def sync_ads(ad_groups):

    for ad_group in ad_groups:

        adset = AdSet(ad_group.platform_adgroup_id)

        ads = adset.get_ads(fields=[
            "id",
            "name",
            "status",
            "creative",
        ])

        for ad in ads:

            creative = ad.get("creative", {})

            Ad.objects.update_or_create(
                ad_group=ad_group,
                platform_ad_id=ad["id"],
                defaults={
                    "name": ad["name"],
                    "status": ad["status"],
                    "headline": creative.get("title"),
                    "primary_text": creative.get("body"),
                }
            )


# ============================================================
# ORCHESTRATOR (RESUMABLE)
# ============================================================

SYNC_STAGES = [
    "FETCH_CAMPAIGNS",
    "UPSERT_CAMPAIGNS",
    "SYNC_ADSETS",
    "SYNC_ADS",
]



def sync_meta_integration(integration):

    state, _ = IntegrationSyncState.objects.get_or_create(
        integration=integration
    )

    # Always initialize SDK
    init_meta_api(integration.access_token)

    for stage in SYNC_STAGES:

        try:

            if stage == "FETCH_CAMPAIGNS":
                meta_campaigns = fetch_meta_campaigns(integration)

            elif stage == "UPSERT_CAMPAIGNS":
                # Always fetch fresh
                meta_campaigns = fetch_meta_campaigns(integration)
                upsert_campaigns(meta_campaigns, integration)

            elif stage == "SYNC_ADSETS":
                platform_campaigns = PlatformCampaign.objects.filter(
                    integration=integration,
                    platform_campaign_id__isnull=False
                )
                sync_adsets(platform_campaigns)

            elif stage == "SYNC_ADS":
                ad_groups = AdGroup.objects.filter(
                    platform_campaign__integration=integration,
                    platform_adgroup_id__isnull=False
                )
                sync_ads(ad_groups)

            state.last_successful_stage = stage
            state.last_error_stage = None
            state.error_message = None
            state.save()

        except Exception as e:
            state.last_error_stage = stage
            state.error_message = str(e)
            state.save()
            raise

