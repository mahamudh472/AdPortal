from datetime import timedelta
import calendar
from django.utils import timezone
from django.db.models import Count
from apps.accounts.models import User
from apps.main.models import Organization, UnifiedCampaign, OrganizationMember
from apps.analysis.models import AnalysisDaily, Report

def get_platform_analysis_data():
    now = timezone.now()
    current_year = now.year
    current_month = now.month

    # ── User Growth (last 6 months) ───────────────────────────────────────
    user_growth = []
    for i in range(5, -1, -1):  # 5 months ago → current month
        month_num = current_month - i
        year = current_year
        while month_num <= 0:
            month_num += 12
            year -= 1

        _, last_day = calendar.monthrange(year, month_num)
        month_start = now.replace(
            year=year, month=month_num, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
        month_end = month_start.replace(
            day=last_day, hour=23, minute=59, second=59, microsecond=999999
        )

        new_users = User.objects.filter(
            joined_at__gte=month_start, joined_at__lte=month_end
        ).count()
        active_users = User.objects.filter(
            last_login__gte=month_start, last_login__lte=month_end
        ).count()

        user_growth.append({
            'month': month_start.strftime('%b'),
            'new_users': new_users,
            'active_users': active_users,
        })

    # ── Feature Usage ─────────────────────────────────────────────────────
    total_orgs = Organization.objects.count()

    def usage_pct(count):
        if total_orgs == 0:
            return 0.0
        return round((count / total_orgs) * 100, 1)

    orgs_with_campaigns = (
        UnifiedCampaign.objects.values('organization').distinct().count()
    )
    orgs_with_analytics = (
        AnalysisDaily.objects.values('organization').distinct().count()
    )
    orgs_with_reports = (
        Report.objects.values('organization').distinct().count()
    )
    # Orgs that have more than one member = team collaboration enabled
    orgs_with_teams = (
        OrganizationMember.objects
        .values('organization')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
        .count()
    )
    feature_usage = [
        {'feature': 'Campaign Creation', 'usage': usage_pct(orgs_with_campaigns)},
        {'feature': 'Analytics', 'usage': usage_pct(orgs_with_analytics)},
        {'feature': 'Reports', 'usage': usage_pct(orgs_with_reports)},
        {'feature': 'Team Collaboration', 'usage': usage_pct(orgs_with_teams)},
    ]

    # ── Aggregate Stats with Trends & Sparklines ─────────────────────────
    # Define current 6 months start / end
    first_month_num = current_month - 5
    first_year = current_year
    while first_month_num <= 0:
        first_month_num += 12
        first_year -= 1
    current_6_months_start = now.replace(
        year=first_year, month=first_month_num, day=1,
        hour=0, minute=0, second=0, microsecond=0
    )
    current_6_months_end = now

    # Define previous 6-month boundaries
    previous_6_months_start = (current_6_months_start - timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    prev_month_num = previous_6_months_start.month - 5
    prev_year = previous_6_months_start.year
    while prev_month_num <= 0:
        prev_month_num += 12
        prev_year -= 1
    previous_6_months_start = previous_6_months_start.replace(
        year=prev_year, month=prev_month_num
    )
    previous_6_months_end = current_6_months_start - timedelta(microseconds=1)

    # 1. Total New Users
    curr_new_users_total = sum(ug['new_users'] for ug in user_growth)
    prev_new_users_total = User.objects.filter(
        joined_at__gte=previous_6_months_start,
        joined_at__lte=previous_6_months_end
    ).count()

    def calculate_trend(current, previous):
        if previous > 0:
            pct = float((current - previous) / previous * 100)
            sign = "+" if pct > 0 else ""
            return f"{sign}{pct:.1f}%", "up" if pct > 0 else ("down" if pct < 0 else "neutral")
        elif previous == 0 and current > 0:
            return "+100.0%", "up"
        else:
            return "0%", "neutral"

    new_users_trend_pct, new_users_trend_dir = calculate_trend(curr_new_users_total, prev_new_users_total)

    # 2. Avg Active Users
    sparkline_active_users = [ug['active_users'] for ug in user_growth]
    curr_avg_active = sum(sparkline_active_users) / 6.0

    prev_active_users = []
    for i in range(11, 5, -1):
        pm_num = current_month - i
        py = current_year
        while pm_num <= 0:
            pm_num += 12
            py -= 1
        _, p_last_day = calendar.monthrange(py, pm_num)
        pm_start = now.replace(
            year=py, month=pm_num, day=1,
            hour=0, minute=0, second=0, microsecond=0
        )
        pm_end = pm_start.replace(day=p_last_day, hour=23, minute=59, second=59, microsecond=999999)
        pm_act = User.objects.filter(last_login__gte=pm_start, last_login__lte=pm_end).count()
        prev_active_users.append(pm_act)
    prev_avg_active = sum(prev_active_users) / 6.0

    active_users_trend_pct, active_users_trend_dir = calculate_trend(curr_avg_active, prev_avg_active)

    # 3. Churned Users
    curr_churned = User.objects.filter(
        last_login__gte=previous_6_months_start,
        last_login__lte=previous_6_months_end
    ).exclude(
        last_login__gte=current_6_months_start,
        last_login__lte=current_6_months_end
    ).count()

    pre_previous_6_months_start = (previous_6_months_start - timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    ppm_num = pre_previous_6_months_start.month - 5
    ppm_year = pre_previous_6_months_start.year
    while ppm_num <= 0:
        ppm_num += 12
        ppm_year -= 1
    pre_previous_6_months_start = pre_previous_6_months_start.replace(
        year=ppm_year, month=ppm_num
    )
    pre_previous_6_months_end = previous_6_months_start - timedelta(microseconds=1)

    prev_churned = User.objects.filter(
        last_login__gte=pre_previous_6_months_start,
        last_login__lte=pre_previous_6_months_end
    ).exclude(
        last_login__gte=previous_6_months_start,
        last_login__lte=previous_6_months_end
    ).count()

    churned_trend_pct, churned_trend_dir = calculate_trend(curr_churned, prev_churned)

    # 4. Most Used Feature
    most_used = max(feature_usage, key=lambda x: x['usage']) if feature_usage else {'feature': 'Campaign Creation', 'usage': 0.0}

    summary = {
        'total_new_users': {
            'value': curr_new_users_total,
            'previous_period': prev_new_users_total,
            'trend_percentage': new_users_trend_pct,
            'trend_direction': new_users_trend_dir,
            'sparkline': [ug['new_users'] for ug in user_growth]
        },
        'avg_active_users': {
            'value': round(curr_avg_active, 1),
            'previous_period': round(prev_avg_active, 1),
            'trend_percentage': active_users_trend_pct,
            'trend_direction': active_users_trend_dir,
            'sparkline': sparkline_active_users
        },
        'churned_users': {
            'value': curr_churned,
            'previous_period': prev_churned,
            'trend_percentage': churned_trend_pct,
            'trend_direction': churned_trend_dir
        },
        'most_used_feature': {
            'name': most_used['feature'],
            'usage_percent': most_used['usage']
        }
    }

    return {
        'user_growth': user_growth,
        'feature_usage': feature_usage,
        'summary': summary
    }
