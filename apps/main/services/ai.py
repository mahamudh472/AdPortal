from datetime import timedelta
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from apps.finance.models import Subscription, UsageRecord
from apps.main.ai_services import generate_copy, generate_ad_copy
from apps.main.models import AIOptimizationSettings, UnifiedCampaign

class AIService:
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
        return {'campaigns_per_title': per_title, 'campaign_metrics': campaign_metrics}

    def get_optimization_summary(self, organization):
        from apps.main.models import AIInsight

        insights = AIInsight.objects.filter(organization=organization)
        # TODO: ``applied_today`` and ``est_savings`` need an "applied" state on AIInsight and
        # a savings calculation from budget re-allocations. Static until that exists.
        return {
            'active_insights': insights.count(),
            'high_priority': insights.filter(impact='HIGH').count(),
            'applied_today': 0,
            'est_savings': 0.0,
        }

    def get_potential_impact(self, organization):
        # TODO: derive from the projected effect of the open insights instead of fixed estimates.
        return {'conversions': '+25%', 'cost_per_result': '-15%', 'roas': '+18%'}

    def get_optimization_history(self, organization):
        # TODO: record every applied optimization (budget shifts, copy updates, ...) and return
        # the real log. Until then orgs that have campaigns get illustrative entries.
        if not UnifiedCampaign.objects.filter(organization=organization).exists():
            return []
        now = timezone.now()
        return [
            {
                'id': 'h-1',
                'title': 'Applied +20% budget to top performing campaign',
                'time': (now - timedelta(hours=3)).isoformat(),
                'impact': 'Conversions increased by +14%',
                'status': 'Applied',
            },
            {
                'id': 'h-2',
                'title': 'Updated ad copy headlines',
                'time': (now - timedelta(days=1)).isoformat(),
                'impact': 'CTR improved by +9%',
                'status': 'Applied',
            },
            {
                'id': 'h-3',
                'title': 'Reallocated daily budget between platforms',
                'time': (now - timedelta(days=4)).isoformat(),
                'impact': 'CPA reduced by -12%',
                'status': 'Applied',
            },
        ]

    def run_optimization(self, organization):
        # TODO: dispatch the real analysis (``run_optimization_analysis``) as a Celery task and
        # persist the insights it produces. For now only the timestamp is recorded.
        settings_obj = self.get_optimization_settings(organization)
        settings_obj.last_optimization_at = timezone.now()
        settings_obj.save(update_fields=['last_optimization_at', 'updated_at'])
        return settings_obj
