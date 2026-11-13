from datetime import timedelta
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from apps.finance.models import Subscription, UsageRecord
from apps.main.ai_services import generate_copy, generate_ad_copy
from apps.main.models import AIOptimizationSettings, UnifiedCampaign

class AIService:
    def _enforce_daily_cap(self, organization):
        """Hard per-organization daily ceiling on paid LLM calls (cost protection)."""
        from django.conf import settings
        from django.core.cache import cache
        from rest_framework.exceptions import Throttled
        limit = getattr(settings, 'AI_DAILY_LIMIT_PER_ORG', 0)
        if not organization or not limit:
            return
        key = f"ai_daily:{organization.pk}:{timezone.now():%Y%m%d}"
        cache.add(key, 0, 24 * 3600)
        try:
            used = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 24 * 3600)
            used = 1
        if used > limit:
            raise Throttled(detail="Daily AI generation limit reached for your organization. Try again tomorrow.")

    def increment_ai_usage(self, organization):
        """Increment the ai_copy_generator UsageRecord for the org's active billing period."""
        subscription = (
            Subscription.objects
            .filter(organization=organization, status__in=['active', 'trialing'])
            .order_by('-created_at')
            .first()
        )
        if not subscription or not subscription.current_period_start:
            return
        record, _ = UsageRecord.objects.get_or_create(
            organization=organization,
            subscription=subscription,
            feature_key='ai_copy_generator',
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            defaults={'used': 0},
        )
        UsageRecord.objects.filter(pk=record.pk).update(used=models.F('used') + 1)

    def generate_copy(self, organization, product, audience, benefits, tone, copy_type):
        self._enforce_daily_cap(organization)
        generated_copy = generate_copy(
            product=product,
            audience=audience,
            benefits=benefits,
            tone=tone,
            copy_type=copy_type
        )
        if organization:
            self.increment_ai_usage(organization)
        return generated_copy

    def generate_ad_copy(self, organization, product_service, target_audience, key_benefits, tone):
        self._enforce_daily_cap(organization)
        generated_copy = generate_ad_copy(
            product_service=product_service,
            target_audience=target_audience,
            key_benefits=key_benefits,
            tone=tone
        )
        if organization:
            self.increment_ai_usage(organization)
        return generated_copy

    def get_ai_insights_queryset(self, organization):
        return organization.ai_insights.order_by('-created_at')

    # ── AI Tools → Optimization page ─────────────────────────────────────────
    def get_optimization_settings(self, organization):
        settings_obj, _ = AIOptimizationSettings.objects.get_or_create(organization=organization)
        return settings_obj

    def get_insight_serializer_context(self, organization, insights):
        """Context the AIInsightDetailSerializer needs (kept to two queries per page)."""
        from apps.analysis.models import AnalysisDaily

        insights = list(insights)
        titles = [i.title for i in insights]
        per_title = dict(
            organization.ai_insights.filter(title__in=titles)
            .values_list('title')
            .annotate(n=models.Count('campaign_id', distinct=True))
        )
        since = timezone.now().date() - timedelta(days=29)
        campaign_metrics = {}
        for row in (
            AnalysisDaily.objects
            .filter(unified_campaign_id__in={i.campaign_id for i in insights}, date__gte=since)
            .values('unified_campaign_id')
            .annotate(impressions=Sum('impressions'), clicks=Sum('clicks'), spend=Sum('spend'))
        ):
            impressions, clicks, spend = row['impressions'] or 0, row['clicks'] or 0, row['spend'] or 0
            campaign_metrics[row['unified_campaign_id']] = {
                'ctr': (clicks / impressions * 100) if impressions else 0.0,
                'cpc': (spend / clicks) if clicks else 0.0,
            }
        campaign_currencies = dict(
            UnifiedCampaign.objects
            .filter(id__in={i.campaign_id for i in insights if i.campaign_id})
            .values_list('id', 'currency')
        )
        return {
            'campaigns_per_title': per_title,
            'campaign_metrics': campaign_metrics,
            'campaign_currencies': campaign_currencies,
        }

    def get_optimization_summary(self, organization):
        from apps.main.services.optimization import get_optimization_summary
        return get_optimization_summary(organization)

    def get_potential_impact(self, organization):
        from apps.main.services.optimization import get_potential_impact
        return get_potential_impact(organization)

    def get_optimization_history(self, organization):
        from apps.main.services.optimization import get_optimization_history
        return get_optimization_history(organization)

    def run_optimization(self, organization):
        """Queue the rule-based analysis; the task refreshes the open insights."""
        from apps.main.tasks import run_optimization_for_organization_task

        settings_obj = self.get_optimization_settings(organization)
        run_optimization_for_organization_task.delay(organization.id)
        settings_obj.last_optimization_at = timezone.now()
        settings_obj.save(update_fields=['last_optimization_at', 'updated_at'])
        return settings_obj
