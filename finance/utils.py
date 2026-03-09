from django.db.models import F

from finance.models import Subscription, UsageRecord


def increment_campaign_usage(organization):
    """Increment the campaign_limit UsageRecord for the org's active billing period.

    Called whenever a new UnifiedCampaign is created — either when a draft is
    published through the portal or when a campaign is discovered during a
    platform sync (Meta / TikTok).  Updating an existing campaign or adding a
    new PlatformCampaign to an already-tracked UnifiedCampaign does NOT call
    this function.
    """
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
        feature_key='campaign_limit',
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        defaults={'used': 0},
    )
    UsageRecord.objects.filter(pk=record.pk).update(used=F('used') + 1)
