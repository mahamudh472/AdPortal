from django.db import models
from apps.finance.models import Subscription, UsageRecord
from apps.main.ai_services import generate_copy, generate_ad_copy

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
