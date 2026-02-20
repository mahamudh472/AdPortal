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
        # Budget (safe)
        # -------------------------------------------------
        if meta_campaign.get("daily_budget"):

            CampaignBudget.objects.update_or_create(
                campaign=platform_campaign.unified_campaign,
                platform=integration.platform,
                defaults={
                    "budget_type": "DAILY",
                    "daily_budget_minor": int(meta_campaign["daily_budget"]),
                    "start_date": meta_campaign.get("start_time")[:10],
                    "run_continuously": not meta_campaign.get("stop_time"),
                }
            )

        platform_campaigns.append(platform_campaign)

    return platform_campaigns


# ============================================================
# STAGE 3: SYNC ADSETS
# ============================================================

def sync_adsets(platform_campaigns):

    all_adgroups = []

    for platform_campaign in platform_campaigns:

        campaign = Campaign(platform_campaign.platform_campaign_id)

        adsets = campaign.get_ad_sets(fields=[
            "id",
            "name",
            "status",
            "daily_budget",
            "targeting",
            "start_time",
            "end_time",
        ])

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

