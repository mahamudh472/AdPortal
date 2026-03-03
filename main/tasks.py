from celery import shared_task
from main.utils.meta_engine.sync_ad import sync_meta_integration
from main.utils.tiktok_engine.sync_ad import sync_tiktok_integration
from main.models import AdIntegration
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def toggle_campaign_status_task(self, unified_campaign_id: int, target_status: str):
    """
    Background task that propagates a PAUSE / ACTIVE toggle to every
    connected ad platform (META, TIKTOK).  Google is skipped until supported.

    Args:
        unified_campaign_id: PK of the UnifiedCampaign.
        target_status: "ACTIVE" or "PAUSED".
    """
    from main.utils.meta_engine.manage_ad import toggle_campaign_status_on_meta
    from main.utils.tiktok_engine.manage_ad import toggle_campaign_status_on_tiktok
    from main.models import PlatformCampaign

    logger.info(
        "toggle_campaign_status_task: campaign=%s target=%s",
        unified_campaign_id, target_status,
    )

    all_errors: list[dict] = []

    platforms = (
        PlatformCampaign.objects
        .filter(unified_campaign_id=unified_campaign_id)
        .values_list("integration__platform", flat=True)
        .distinct()
    )

    for platform in platforms:
        try:
            if platform == "META":
                errs = toggle_campaign_status_on_meta(unified_campaign_id, target_status)
            elif platform == "TIKTOK":
                errs = toggle_campaign_status_on_tiktok(unified_campaign_id, target_status)
            else:
                logger.info("toggle_campaign_status_task: skipping unsupported platform %s", platform)
                continue
            all_errors.extend(errs)
        except Exception as exc:
            logger.error(
                "toggle_campaign_status_task: platform=%s campaign=%s error=%s",
                platform, unified_campaign_id, exc,
            )
            all_errors.append({"platform": platform, "error": str(exc)})
            self.retry(exc=exc, countdown=60)

    if all_errors:
        logger.warning(
            "toggle_campaign_status_task completed with errors: %s", all_errors
        )
    else:
        logger.info("toggle_campaign_status_task completed successfully for campaign %s", unified_campaign_id)



@shared_task(bind=True, max_retries=3)
def sync_ads_task(self, platform_integration_id):
    """Background task to sync ads for a given platform integration."""
    logger.info("sync_ads_task started for integration_id=%s", platform_integration_id)
    try:
        platform_integration = AdIntegration.objects.get(id=platform_integration_id)
    except AdIntegration.DoesNotExist:
        logger.warning("Integration %s does not exist, skipping.", platform_integration_id)
        return
    logger.info("Syncing platform=%s, account=%s", platform_integration.platform, platform_integration.ad_account_id)
    try:
        if platform_integration.platform.upper() == 'META':
            sync_meta_integration(platform_integration)
            logger.info("Meta sync completed for integration %s", platform_integration_id)
        elif platform_integration.platform.upper() == 'TIKTOK':
            sync_tiktok_integration(platform_integration)
            logger.info("TikTok sync completed for integration %s", platform_integration_id)
        else:
            logger.warning("Unsupported platform: %s — skipping", platform_integration.platform)
            return
    except Exception as exc:
        logger.error("sync_ads_task failed for integration %s: %s", platform_integration_id, exc)
        self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def sync_analytics_task(self, platform_integration_id, start_date=None, end_date=None):
    """Background task to sync analytics for a given platform integration."""
    from datetime import datetime

    try:
        integration = AdIntegration.objects.get(id=platform_integration_id)
    except AdIntegration.DoesNotExist:
        return

    sd = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    ed = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    try:
        if integration.platform.upper() == 'META':
            from main.utils.meta_engine.analysis import generate_meta_campaign_analysis
            # Meta analysis uses platform_campaign_ids
            from main.models import PlatformCampaign
            pc_ids = list(
                PlatformCampaign.objects.filter(
                    integration=integration,
                    platform_campaign_id__isnull=False,
                ).values_list("platform_campaign_id", flat=True)
            )
            if pc_ids:
                generate_meta_campaign_analysis(integration, pc_ids, sd, ed)

        elif integration.platform.upper() == 'TIKTOK':
            from main.utils.tiktok_engine.analysis import generate_tiktok_campaign_analysis
            generate_tiktok_campaign_analysis(integration, sd, ed)

        else:
            logger.warning("sync_analytics_task: unsupported platform %s — skipping", integration.platform)
            return

    except Exception as exc:
        logger.error("sync_analytics_task failed for integration %s: %s", platform_integration_id, exc)
        self.retry(exc=exc, countdown=60)
