from django.db.models import Q
from apps.accounts.models import User
from django.utils import timezone
from datetime import timedelta

def get_user_stats():
    from apps.admin_dashboard.utils import get_percentage
    from apps.main.models import OrganizationStatusChoices, OrganizationMember

    all_users = User.objects.all()
    total_users = all_users.count()
    past_date = timezone.now() - timedelta(days=7)
    last_week_created = all_users.filter(joined_at__gte=past_date).count()
    active_users = all_users.filter(is_active=True).count()
    suspended_users = all_users.filter(status='suspended').count()

    # Calculate trial users dynamically (owners or active members of trial organizations)
    trial_owners = User.objects.filter(owned_organizations__status=OrganizationStatusChoices.TRIAL).values_list('id', flat=True)
    trial_members = OrganizationMember.objects.filter(organization__status=OrganizationStatusChoices.TRIAL, status='ACTIVE').values_list('user_id', flat=True)
    trial_user_ids = list(set(trial_owners) | {uid for uid in trial_members if uid is not None})
    trial_users = User.objects.filter(id__in=trial_user_ids).count()

    return {
        'total_users': {
            'value': total_users,
            'last_week': last_week_created,
        },
        "active_users": active_users,
        "suspended_users": suspended_users,
        "trial_users": trial_users
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
