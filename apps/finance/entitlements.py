"""Plan entitlements (audit SEC-13).

Limits are enforced only when the organization has an active/trialing subscription
whose plan defines an integer limit; organizations without a subscription or with an
"unlimited" feature are never blocked, so existing accounts keep working.
"""
from django.db.models import Sum

from apps.finance.models import Subscription


def active_subscription(organization):
    return (
        Subscription.objects.filter(organization=organization, status__in=['active', 'trialing'])
        .select_related('plan')
        .order_by('-created_at')
        .first()
    )


def campaign_quota(organization):
    """Return (used, limit) — limit is None when unlimited / not enforced."""
    sub = active_subscription(organization)
    if not sub:
        return 0, None
    limit = sub.plan.get_campaign_limit()
    if not isinstance(limit, int) or isinstance(limit, bool):
        return 0, None
    used = (
        sub.usage_records.filter(feature_key='campaign_limit').aggregate(t=Sum('used'))['t'] or 0
    )
    return used, limit


def can_publish_campaign(organization) -> bool:
    used, limit = campaign_quota(organization)
    return limit is None or used < limit


def can_add_team_member(organization) -> bool:
    from apps.main.models import OrganizationMember, TeamInvitation
    from datetime import timedelta
    from django.utils import timezone

    sub = active_subscription(organization)
    if not sub:
        return True
    limit = sub.plan.get_team_member_limit()
    if not isinstance(limit, int) or isinstance(limit, bool):
        return True
    members = OrganizationMember.objects.filter(organization=organization).count()
    pending = TeamInvitation.objects.filter(
        organization=organization, status='PENDING',
        created_at__gte=timezone.now() - timedelta(days=7),
    ).count()
    return members + pending < limit
