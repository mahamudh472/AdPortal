from django.db.models import Q
from apps.accounts.models import User
from django.utils import timezone
from datetime import timedelta

def get_user_stats():

    all_users = User.objects.all()
    total_users = all_users.count()
    past_date = timezone.now() - timedelta(days=7)
    last_week_created = all_users.filter(joined_at__gte=past_date).count()
    active_users = all_users.filter(is_active=True).count()
    suspended_users = all_users.filter(status='suspended').count()

    # TODO: Need to make this dynamic
    trial_users = 0

    return {
        'total_users': {
            'value': total_users,
            'last_week': last_week_created,
            "trend_percentage": "+0%",
            "trend_direction": "neutral"
        },
        "active_users": {
            "value": active_users,
            "previous_period": 0,
            "trend_percentage": "+100%",
            "trend_direction": "up"
        },
        "suspended_users": {
            "value": suspended_users,
            "previous_period": 0,
            "trend_percentage": "0%",
            "trend_direction": "neutral"
        },
        "trial_users": {
            "value": trial_users,
            "previous_period": 0,
            "trend_percentage": "0%",
            "trend_direction": "neutral"
        }
    }

def get_user_list(request):
    q = request.query_params.get('search', '')
    status = request.query_params.get('status', '').lower()
    role = request.query_params.get('role', '').lower()

    filters = Q()
    if q != '':
        filters &= Q(full_name__icontains=q) | Q(email__icontains=q)
    if status in ['active', 'inactive', 'suspended']:
        filters &= Q(status=status)
    if role == 'admin':
        filters &= Q(is_staff=True)
    elif role == 'user':
        filters &= Q(is_staff=False)

    return User.objects.filter(filters)
