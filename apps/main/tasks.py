from celery import shared_task
from apps.main.utils.meta_engine.sync_ad import sync_meta_integration
from apps.main.utils.tiktok_engine.sync_ad import sync_tiktok_integration
from apps.main.utils.google_engine.sync_ad import sync_google_integration
from apps.main.models import (
    AdIntegration,
    PlatformSyncOperation,
    PlatformSyncStatus,
)
from apps.main.utils.sync_events import (
    create_platform_sync_event,
    mark_platform_sync_event_failed,
    mark_platform_sync_event_in_progress,
    mark_platform_sync_event_success,
)
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Avg

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def sync_campaign_to_platforms_task(self, campaign_id: int, operation: str):
    """
    Background task that pushes a campaign create/update operation
    to all connected platforms for that campaign.
    """
    from apps.main.models import UnifiedCampaign
    from apps.main.utils.meta_engine.manage_ad import create_ad_on_meta, update_campaign_on_meta
    from apps.main.utils.google_engine.manage_ad import create_ad_on_google, update_campaign_on_google
    from apps.main.utils.tiktok_handler import create_full_ad_for_tiktok

    if operation not in (PlatformSyncOperation.CREATE, PlatformSyncOperation.UPDATE):
        raise ValueError(f"Unsupported campaign sync operation: {operation}")

    campaign = UnifiedCampaign.objects.select_related("organization").filter(id=campaign_id).first()
    if not campaign:
        logger.warning("sync_campaign_to_platforms_task: campaign %s not found", campaign_id)
        return

    integrations = AdIntegration.objects.filter(
        organization=campaign.organization,
        is_active=True,
    ).order_by("platform", "-created_at", "-id")

    handled_platforms: set[str] = set()
    for integration in integrations:
        platform = integration.platform
        if platform in handled_platforms:
            continue
        handled_platforms.add(platform)

        event = create_platform_sync_event(
            campaign=campaign,
            integration=integration,
            platform=platform,
            operation=operation,
            status=PlatformSyncStatus.QUEUED,
            message=f"{operation} scheduled for {platform}",
            payload={"campaign_id": campaign.id},
        )
        mark_platform_sync_event_in_progress(
            event,
            message=f"{operation} in progress for {platform}",
        )

        try:
            if platform == "META":
                if operation == PlatformSyncOperation.CREATE:
                    ad = create_ad_on_meta(campaign.id)
                    mark_platform_sync_event_success(
                        event,
                        message="Meta campaign create completed",
                        payload={
                            "campaign_id": campaign.id,
                            "ad_id": getattr(ad, "id", None),
                            "platform_ad_id": getattr(ad, "platform_ad_id", None),
                        },
                    )
                else:
                    result = update_campaign_on_meta(campaign.id)
                    mark_platform_sync_event_success(
                        event,
                        message="Meta campaign update completed",
                        payload={
                            "campaign_id": campaign.id,
                            "ad_id": getattr(result, "id", None) if result else None,
                            "platform_ad_id": getattr(result, "platform_ad_id", None) if result else None,
                        },
                    )

            elif platform == "GOOGLE":
                if operation == PlatformSyncOperation.CREATE:
                    ad = create_ad_on_google(campaign.id)
                    mark_platform_sync_event_success(
                        event,
                        message="Google campaign create completed",
                        payload={
                            "campaign_id": campaign.id,
                            "ad_id": getattr(ad, "id", None),
                            "platform_ad_id": getattr(ad, "platform_ad_id", None),
                        },
                    )
                else:
                    result = update_campaign_on_google(campaign.id)
                    mark_platform_sync_event_success(
                        event,
                        message="Google campaign update completed",
                        payload={
                            "campaign_id": campaign.id,
                            "ad_id": getattr(result, "id", None) if result else None,
                            "platform_ad_id": getattr(result, "platform_ad_id", None) if result else None,
                        },
                    )

            elif platform == "TIKTOK":
                from apps.main.models import PlatformCampaign

                existing_tiktok_campaign = PlatformCampaign.objects.filter(
                    unified_campaign=campaign,
                    integration=integration,
                    platform_campaign_id__isnull=False,
                ).exists()
                result = create_full_ad_for_tiktok(
                    campaign,
                    integration,
                    force_recreate_campaign=(operation == PlatformSyncOperation.CREATE or not existing_tiktok_campaign),
                    update_existing_campaign=(operation == PlatformSyncOperation.UPDATE and existing_tiktok_campaign),
                )
                mark_platform_sync_event_success(
                    event,
                    message=f"TikTok campaign {operation.lower()} completed",
                    payload={"campaign_id": campaign.id, **(result or {})},
                )
            else:
                mark_platform_sync_event_failed(
                    event,
                    error_message=f"Unsupported platform: {platform}",
                    message="Operation skipped",
                )
        except Exception as exc:
            logger.error(
                "sync_campaign_to_platforms_task: platform=%s campaign=%s operation=%s error=%s",
                platform,
                campaign.id,
                operation,
                exc,
            )
            mark_platform_sync_event_failed(
                event,
                error_message=str(exc),
                message=f"{operation} failed for {platform}",
                payload={"campaign_id": campaign.id},
            )


@shared_task(bind=True, max_retries=3)
def delete_campaign_from_platforms_task(self, platform_campaign_ids: list):
    """
    Background task that deletes / archives a campaign on every connected
    platform after the local UnifiedCampaign has already been removed from DB.

    Args:
        platform_campaign_ids: List of PlatformCampaign PKs whose
            platform_campaign_id and integration details we still need to
            act on.  These rows are fetched by PK so the task can be
            re-tried safely even if the unified campaign is gone.
    """
    from apps.main.models import PlatformCampaign

    logger.info(
        "delete_campaign_from_platforms_task: handling %d platform campaign(s)",
        len(platform_campaign_ids),
    )

    for pc_id in platform_campaign_ids:
        pc = PlatformCampaign.objects.select_related("integration").filter(id=pc_id).first()
        if not pc:
            logger.warning("delete_campaign_from_platforms_task: PlatformCampaign %s not found", pc_id)
            continue

        platform = pc.integration.platform
        platform_campaign_id = pc.platform_campaign_id

        try:
            if platform == "META":
                from apps.main.utils.meta_engine.manage_ad import delete_campaign_on_meta
                delete_campaign_on_meta(platform_campaign_id, pc.integration)

            elif platform == "GOOGLE":
                from apps.main.utils.google_engine.manage_ad import delete_campaign_on_google
                delete_campaign_on_google(platform_campaign_id, pc.integration)

            elif platform == "TIKTOK":
                from apps.main.utils.tiktok_engine.manage_ad import delete_campaign_on_tiktok
                delete_campaign_on_tiktok(platform_campaign_id, pc.integration)

            else:
                logger.warning(
                    "delete_campaign_from_platforms_task: unsupported platform %s — skipping", platform
                )
                continue

            logger.info(
                "delete_campaign_from_platforms_task: deleted campaign %s on %s",
                platform_campaign_id, platform,
            )

        except Exception as exc:
            logger.error(
                "delete_campaign_from_platforms_task: failed to delete campaign %s on %s: %s",
                platform_campaign_id, platform, exc,
            )
            self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def toggle_campaign_status_task(self, unified_campaign_id: int, target_status: str):
    """
    Background task that propagates a PAUSE / ACTIVE toggle to every
    connected ad platform (META, TIKTOK, GOOGLE).

    Args:
        unified_campaign_id: PK of the UnifiedCampaign.
        target_status: "ACTIVE" or "PAUSED".
    """
    from apps.main.utils.meta_engine.manage_ad import toggle_campaign_status_on_meta
    from apps.main.utils.tiktok_engine.manage_ad import toggle_campaign_status_on_tiktok
    from apps.main.utils.google_engine.manage_ad import toggle_campaign_status_on_google
    from apps.main.models import PlatformCampaign, UnifiedCampaign

    logger.info(
        "toggle_campaign_status_task: campaign=%s target=%s",
        unified_campaign_id, target_status,
    )

    campaign = UnifiedCampaign.objects.filter(id=unified_campaign_id).first()
    if not campaign:
        logger.warning("toggle_campaign_status_task: campaign %s not found", unified_campaign_id)
        return

    all_errors: list[dict] = []

    platforms = (
        PlatformCampaign.objects
        .filter(unified_campaign_id=unified_campaign_id)
        .values_list("integration__platform", flat=True)
        .distinct()
    )

    for platform in platforms:
        integration = AdIntegration.objects.filter(
            organization=campaign.organization,
            platform=platform,
            is_active=True,
        ).order_by("-created_at", "-id").first()

        event = create_platform_sync_event(
            campaign=campaign,
            integration=integration,
            platform=platform,
            operation=PlatformSyncOperation.TOGGLE_STATUS,
            message=f"Status toggle requested: {target_status}",
            payload={"target_status": target_status},
        )
        mark_platform_sync_event_in_progress(
            event,
            message=f"Applying status={target_status} on {platform}",
            payload={"target_status": target_status},
        )

        try:
            if platform == "META":
                errs = toggle_campaign_status_on_meta(unified_campaign_id, target_status)
            elif platform == "TIKTOK":
                errs = toggle_campaign_status_on_tiktok(unified_campaign_id, target_status)
            elif platform == "GOOGLE":
                errs = toggle_campaign_status_on_google(unified_campaign_id, target_status)
            else:
                logger.info("toggle_campaign_status_task: skipping unsupported platform %s", platform)
                mark_platform_sync_event_failed(
                    event,
                    error_message=f"Unsupported platform: {platform}",
                    message="Toggle skipped",
                    payload={"target_status": target_status},
                )
                continue
            all_errors.extend(errs)
            if errs:
                mark_platform_sync_event_failed(
                    event,
                    error_message="; ".join([e.get("error", "Unknown error") for e in errs]),
                    message=f"Toggle partially failed on {platform}",
                    payload={"target_status": target_status, "errors": errs},
                )
            else:
                mark_platform_sync_event_success(
                    event,
                    message=f"Status set to {target_status} on {platform}",
                    payload={"target_status": target_status},
                )
        except Exception as exc:
            logger.error(
                "toggle_campaign_status_task: platform=%s campaign=%s error=%s",
                platform, unified_campaign_id, exc,
            )
            all_errors.append({"platform": platform, "error": str(exc)})
            mark_platform_sync_event_failed(
                event,
                error_message=str(exc),
                message=f"Toggle failed on {platform}",
                payload={"target_status": target_status},
            )
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

    campaign_ids = list(
        platform_integration.platform_campaigns.values_list("unified_campaign_id", flat=True).distinct()
    )
    events = []
    for campaign_id in campaign_ids:
        campaign_obj = None
        if campaign_id:
            from apps.main.models import UnifiedCampaign

            campaign_obj = UnifiedCampaign.objects.filter(id=campaign_id).first()
        if campaign_obj:
            event = create_platform_sync_event(
                campaign=campaign_obj,
                integration=platform_integration,
                platform=platform_integration.platform,
                operation=PlatformSyncOperation.SYNC_ADS,
                message="Ads sync queued",
                payload={"integration_id": platform_integration.id},
            )
            mark_platform_sync_event_in_progress(
                event,
                message="Ads sync in progress",
                payload={"integration_id": platform_integration.id},
            )
            events.append(event)
    try:
        if platform_integration.platform.upper() == 'META':
            from apps.main.utils.meta_engine.sync_ad import MetaSyncConfigError

            try:
                sync_meta_integration(platform_integration)
            except MetaSyncConfigError as exc:
                logger.error(
                    "Meta sync skipped due to configuration error for integration %s: %s",
                    platform_integration_id,
                    exc,
                )
                from apps.accounts.notifications import notify_admins
                notify_admins(
                    f"Meta sync skipped for integration {platform_integration_id}: {exc}",
                    setting_key='system_errors',
                )
                return
            logger.info("Meta sync completed for integration %s", platform_integration_id)
        elif platform_integration.platform.upper() == 'TIKTOK':
            sync_tiktok_integration(platform_integration)
            logger.info("TikTok sync completed for integration %s", platform_integration_id)
        elif platform_integration.platform.upper() == 'GOOGLE':
            sync_google_integration(platform_integration)
            logger.info("Google sync completed for integration %s", platform_integration_id)
        else:
            logger.warning("Unsupported platform: %s — skipping", platform_integration.platform)
            for event in events:
                mark_platform_sync_event_failed(
                    event,
                    error_message=f"Unsupported platform: {platform_integration.platform}",
                    message="Ads sync skipped",
                    payload={"integration_id": platform_integration.id},
                )
            return
        for event in events:
            mark_platform_sync_event_success(
                event,
                message="Ads sync completed",
                payload={"integration_id": platform_integration.id},
            )
    except Exception as exc:
        logger.error("sync_ads_task failed for integration %s: %s", platform_integration_id, exc)
        for event in events:
            mark_platform_sync_event_failed(
                event,
                error_message=str(exc),
                message="Ads sync failed",
                payload={"integration_id": platform_integration.id},
            )
        from apps.accounts.notifications import notify_admins
        notify_admins(
            f"Platform sync failed for {platform_integration.platform} integration "
            f"(account: {platform_integration.ad_account_id}): {exc}",
            setting_key='system_errors',
        )
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

    campaign_ids = list(
        integration.platform_campaigns.values_list("unified_campaign_id", flat=True).distinct()
    )
    events = []
    for campaign_id in campaign_ids:
        from apps.main.models import UnifiedCampaign

        campaign = UnifiedCampaign.objects.filter(id=campaign_id).first()
        if not campaign:
            continue
        event = create_platform_sync_event(
            campaign=campaign,
            integration=integration,
            platform=integration.platform,
            operation=PlatformSyncOperation.SYNC_ANALYTICS,
            message="Analytics sync queued",
            payload={"integration_id": integration.id, "start_date": start_date, "end_date": end_date},
        )
        mark_platform_sync_event_in_progress(
            event,
            message="Analytics sync in progress",
            payload={"integration_id": integration.id, "start_date": start_date, "end_date": end_date},
        )
        events.append(event)

    try:
        if integration.platform.upper() == 'META':
            from apps.main.utils.meta_engine.analysis import generate_meta_campaign_analysis
            # Meta analysis uses platform_campaign_ids
            from apps.main.models import PlatformCampaign
            pc_ids = list(
                PlatformCampaign.objects.filter(
                    integration=integration,
                    platform_campaign_id__isnull=False,
                ).values_list("platform_campaign_id", flat=True)
            )
            if pc_ids:
                generate_meta_campaign_analysis(integration, pc_ids, sd, ed)

        elif integration.platform.upper() == 'TIKTOK':
            from apps.main.utils.tiktok_engine.analysis import generate_tiktok_campaign_analysis
            generate_tiktok_campaign_analysis(integration, sd, ed)

        elif integration.platform.upper() == 'GOOGLE':
            from apps.main.utils.google_engine.analysis import generate_google_campaign_analysis
            generate_google_campaign_analysis(integration, sd, ed)

        else:
            logger.warning("sync_analytics_task: unsupported platform %s — skipping", integration.platform)
            for event in events:
                mark_platform_sync_event_failed(
                    event,
                    error_message=f"Unsupported platform: {integration.platform}",
                    message="Analytics sync skipped",
                    payload={"integration_id": integration.id, "start_date": start_date, "end_date": end_date},
                )
            return

        for event in events:
            mark_platform_sync_event_success(
                event,
                message="Analytics sync completed",
                payload={"integration_id": integration.id, "start_date": start_date, "end_date": end_date},
            )

    except Exception as exc:
        logger.error("sync_analytics_task failed for integration %s: %s", platform_integration_id, exc)
        for event in events:
            mark_platform_sync_event_failed(
                event,
                error_message=str(exc),
                message="Analytics sync failed",
                payload={"integration_id": integration.id, "start_date": start_date, "end_date": end_date},
            )
        self.retry(exc=exc, countdown=60)


@shared_task
def weekly_performance_summary_task():
    """
    Sent every Monday morning to org members who have enabled
    NotificationSetting.weekly_performance_summary.

    Aggregates last 7 days of AnalysisDaily spend / impressions / clicks per
    organisation and creates one in-app notification per qualifying member.
    """
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from apps.analysis.models import AnalysisDaily
    from apps.main.models import Organization
    from apps.accounts.notifications import notify_org_members

    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=7)

    organizations = Organization.objects.all()
    for organization in organizations:
        weekly_qs = AnalysisDaily.objects.filter(
            organization=organization,
            date__gte=start_date,
            date__lte=end_date,
        )
        if not weekly_qs.exists():
            continue

        totals = weekly_qs.aggregate(
            total_spend=Sum('spend'),
            total_impressions=Sum('impressions'),
            total_clicks=Sum('clicks'),
        )
        spend = totals['total_spend'] or 0
        impressions = totals['total_impressions'] or 0
        clicks = totals['total_clicks'] or 0

        message = (
            f"Weekly Performance Summary ({start_date} – {end_date}): "
            f"Spend: ${spend:,.2f} | Impressions: {impressions:,} | Clicks: {clicks:,}."
        )
        notify_org_members(
            organization,
            message,
            setting_key='weekly_performance_summary',
            roles=['OWNER', 'ADMIN', 'MEMBER'],
        )
        logger.info(
            "weekly_performance_summary_task: sent summary for org %s", organization.id
        )


@shared_task(bind=True, max_retries=3, soft_time_limit=300, time_limit=360)
def generate_ai_insights_for_active_campaigns(self):
    """Periodic fan-out: queue one independent task per ACTIVE campaign.

    Previously every campaign was processed serially inside one task, so a single failing
    LLM call retried (and duplicated) the whole batch. Now each campaign has its own
    retries and time limit.
    """
    from apps.main.models import UnifiedCampaign

    ids = list(UnifiedCampaign.objects.filter(status="ACTIVE").values_list("id", flat=True))
    if not ids:
        logger.info("generate_ai_insights_for_active_campaigns: no active campaigns found.")
        return
    for campaign_id in ids:
        generate_ai_insights_for_campaign.delay(campaign_id)
    logger.info("generate_ai_insights_for_active_campaigns: queued %d campaigns", len(ids))


@shared_task(bind=True, max_retries=3, soft_time_limit=300, time_limit=360)
def generate_ai_insights_for_campaign(self, campaign_id):
    """Collect 7 days of analytics for one campaign, run the GPT analysis, store AIInsight rows."""
    from apps.main.models import UnifiedCampaign, AIInsight
    from apps.main.ai_services import run_optimization_analysis
    from apps.analysis.models import AnalysisDaily

    end_date   = timezone.now().date()
    start_date = end_date - timedelta(days=7)

    IMPACT_MAP = {
        "high":   "HIGH",
        "medium": "MEDIUM",
        "low":    "LOW",
    }

    campaign = UnifiedCampaign.objects.filter(id=campaign_id, status="ACTIVE").select_related("organization").first()
    if campaign is None:
        return

    logger.info(
        "generate_ai_insights_for_active_campaigns: processing campaign id=%s name='%s'",
        campaign.id, campaign.name,
    )

    # ── 1. Pull the last-7-days analytics rows for this campaign ──────────
    analytics_qs = AnalysisDaily.objects.filter(
        unified_campaign=campaign,
        date__gte=start_date,
        date__lte=end_date,
    )

    if not analytics_qs.exists():
        logger.info(
            "generate_ai_insights_for_active_campaigns: no analytics data for campaign %s — skipping",
            campaign.id,
        )
        return

    # ── 2. Aggregate totals across all platforms for the overview ─────────
    totals = analytics_qs.aggregate(
        total_spend=Sum("spend"),
        total_impressions=Sum("impressions"),
        total_clicks=Sum("clicks"),
        total_conversions=Sum("conversions"),
        avg_ctr=Avg("ctr"),
        avg_cpc=Avg("cpc"),
        avg_cpm=Avg("cpm"),
        avg_cpa=Avg("cpa"),
        avg_roas=Avg("roas"),
    )

    # ── 3. Build per-platform breakdown ───────────────────────────────────
    platform_breakdown = {}
    for row in analytics_qs.values(
        "platform", "campaign_id", "campaign_name",
    ).annotate(
        spend=Sum("spend"),
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        conversions=Sum("conversions"),
        avg_ctr=Avg("ctr"),
        avg_cpc=Avg("cpc"),
        avg_cpm=Avg("cpm"),
        avg_cpa=Avg("cpa"),
        avg_roas=Avg("roas"),
    ):
        platform = row["platform"]
        if platform not in platform_breakdown:
            platform_breakdown[platform] = []
        platform_breakdown[platform].append({
            "campaign_id":   row["campaign_id"],
            "campaign_name": row["campaign_name"],
            "spend":         round(row["spend"] or 0, 2),
            "impressions":   row["impressions"] or 0,
            "clicks":        row["clicks"] or 0,
            "conversions":   row["conversions"] or 0,
            "avg_ctr":       round(row["avg_ctr"] or 0, 4),
            "avg_cpc":       round(row["avg_cpc"] or 0, 2),
            "avg_cpm":       round(row["avg_cpm"] or 0, 2),
            "avg_cpa":       round(row["avg_cpa"] or 0, 2),
            "avg_roas":      round(row["avg_roas"] or 0, 2),
        })

    # ── 4. Assemble the campaign_data payload ─────────────────────────────
    campaign_data = {
        "campaign_overview": {
            "campaign_id":   str(campaign.id),
            "name":          campaign.name,
            "objective":     campaign.objective,
            "status":        campaign.status,
            "currency":      campaign.currency,
            "date_range":    {"start": str(start_date), "end": str(end_date)},
        },
        "summary": {
            "total_spend":       round(totals["total_spend"] or 0, 2),
            "total_impressions": totals["total_impressions"] or 0,
            "total_clicks":      totals["total_clicks"] or 0,
            "total_conversions": totals["total_conversions"] or 0,
            "avg_ctr":           round(totals["avg_ctr"] or 0, 4),
            "avg_cpc":           round(totals["avg_cpc"] or 0, 2),
            "avg_cpm":           round(totals["avg_cpm"] or 0, 2),
            "avg_cpa":           round(totals["avg_cpa"] or 0, 2),
            "avg_roas":          round(totals["avg_roas"] or 0, 2),
        },
        "platform_breakdown": platform_breakdown,
    }

    # ── 5. Run the AI optimisation analysis ───────────────────────────────
    try:
        result = run_optimization_analysis(campaign_data)
    except Exception as exc:
        logger.error(
            "generate_ai_insights_for_active_campaigns: AI analysis failed for campaign %s: %s",
            campaign.id, exc,
        )
        try:
            self.retry(exc=exc, countdown=120)
        except self.MaxRetriesExceededError:
            pass
        return

    if result.get("status") != "success":
        logger.warning(
            "generate_ai_insights_for_active_campaigns: AI returned non-success for campaign %s: %s",
            campaign.id, result.get("message"),
        )
        return

    # ── 6. Persist each optimisation card as an AIInsight ─────────────────
    optimizations = result.get("optimizations", [])
    insights_created = 0

    for opt in optimizations:
        impact_raw = str(opt.get("impact", "medium")).lower()
        impact     = IMPACT_MAP.get(impact_raw, "MEDIUM")

        # Combine observation + recommendation as the description.
        description = (
            f"{opt.get('observation', '')}\n\n"
            f"Recommendation: {opt.get('recommendation', '')}"
        ).strip()

        AIInsight.objects.create(
            organization=campaign.organization,
            campaign=campaign,
            title=opt.get("subject", "AI Optimisation Insight"),
            description=description,
            impact=impact,
        )
        insights_created += 1

    logger.info(
        "generate_ai_insights_for_active_campaigns: created %d insights for campaign id=%s",
        insights_created, campaign.id,
    )
