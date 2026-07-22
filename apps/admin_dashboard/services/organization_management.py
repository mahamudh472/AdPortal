from django.utils import timezone
from datetime import timedelta
from apps.admin_dashboard.utils import get_percentage
from apps.main.models import Organization, OrganizationStatusChoices as status_choices


def _get_organization_stats_for_status(status):
    now = timezone.now()
    past_date = now - timedelta(days=7)
    
    current_count = Organization.objects.filter(status=status).count()
    previous_count = Organization.objects.filter(status=status, created_at__lt=past_date).count()
    
    pct = get_percentage(current_count, previous_count)
    if current_count > previous_count:
        direction = "up"
        percentage = f"+{pct}" if not pct.startswith("+") else pct
    elif current_count < previous_count:
        direction = "down"
        percentage = pct
    else:
        direction = "neutral"
        percentage = "0%"
        
    return {
        "value": current_count,
        "previous_period": previous_count,
        "trend_percentage": percentage,
        "trend_direction": direction
    }


def get_active_organizations():
    """
    Retrieve statistics for active organizations.

    Returns:
        dict: Stats including current count, previous period count, trend percentage, and trend direction.
    """
    return _get_organization_stats_for_status(status_choices.ACTIVE)


def get_suspended_organizations():
    """
    Retrieve statistics for suspended organizations.

    Returns:
        dict: Stats including current count, previous period count, trend percentage, and trend direction.
    """
    return _get_organization_stats_for_status(status_choices.SUSPENDED)


def get_trial_organizations():
    """
    Retrieve statistics for trial organizations.

    Returns:
        dict: Stats including current count, previous period count, trend percentage, and trend direction.
    """
    return _get_organization_stats_for_status(status_choices.TRIAL)

