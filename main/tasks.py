from celery import shared_task
from main.utils.meta_engine.sync_ad import sync_meta_integration
from main.utils.tiktok_engine.sync_ad import sync_tiktok_integration
from main.models import AdIntegration
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Avg

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
        from accounts.notifications import notify_admins
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
    from analysis.models import AnalysisDaily
    from main.models import Organization
    from accounts.notifications import notify_org_members

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


@shared_task(bind=True, max_retries=3)
def generate_ai_insights_for_active_campaigns(self):
    """
    Periodic background task that processes every ACTIVE UnifiedCampaign.

    For each campaign it:
    1. Collects the last 7 days of AnalysisDaily records (aggregated per
       platform and per adgroup).
    2. Builds a structured `campaign_data` dict that mirrors the format
       expected by `run_optimization_analysis`.
    3. Calls `run_optimization_analysis` (GPT-4o powered).
    4. Persists each returned optimisation card as an AIInsight row.

    Intended to be scheduled via Celery Beat (e.g. daily or weekly).
    """
    from main.models import UnifiedCampaign, AIInsight
    from main.ai_services import run_optimization_analysis
    from analysis.models import AnalysisDaily

    end_date   = timezone.now().date()
    start_date = end_date - timedelta(days=7)

    # Map the text labels returned by GPT-4o to the model's valid choices.
    IMPACT_MAP = {
        "high":   "HIGH",
        "medium": "MEDIUM",
        "low":    "LOW",
    }

    active_campaigns = UnifiedCampaign.objects.filter(
        status="ACTIVE"
    ).select_related("organization")

    if not active_campaigns.exists():
        logger.info("generate_ai_insights_for_active_campaigns: no active campaigns found.")
        return

    for campaign in active_campaigns:
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
            continue

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
            continue

        if result.get("status") != "success":
            logger.warning(
                "generate_ai_insights_for_active_campaigns: AI returned non-success for campaign %s: %s",
                campaign.id, result.get("message"),
            )
            continue

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