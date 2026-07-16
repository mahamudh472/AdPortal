from apps.accounts.models import User
from apps.admin_dashboard.utils import get_last_month_objects_count, get_second_last_month_objects_count, get_percentage
from apps.main.models import PlatformCampaign
from apps.finance.models import Payment
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal
from datetime import timedelta
import calendar

def get_users_card_data():
    """
    Get the data for the users card in the admin dashboard.
    {
        "value": 4,
        "past_month": 4,
        "percentage": "100.0",
        "trend": {
            "direction": "up",
            "sparkline": [0, 1, 1, 2, 3, 4]
        }
    }
    """

    users = User.objects.all()
    last_month_users = get_last_month_objects_count(users)
    second_last_month_users = get_second_last_month_objects_count(users)
    user_info_percentage = get_percentage(last_month_users, second_last_month_users)


    now = timezone.now()
    sparkline = []
    for i in range(5, -1, -1):
        start_date = now - timedelta(days=(i + 1) * 7)
        end_date = now - timedelta(days=i * 7)
        count = users.filter(joined_at__gte=start_date, joined_at__lte=end_date).count()
        sparkline.append(count)

    if last_month_users > second_last_month_users:
        direction = "up"
    elif last_month_users < second_last_month_users:
        direction = "down"
    else:
        direction = "neutral"

    return {
        "value": users.count(),
        "past_month": last_month_users,
        "percentage": user_info_percentage,
        "trend": {
            "direction": direction,
            "sparkline": sparkline
        }
    }

def get_campaigns_card_data():
    """
    get the data for the campaigns card in the admin dashboard.
    {
        "value": 6,
        "last_month": 6,
        "percentage": "100.0"
        "percentage": "100.0",
        "trend": {
            "direction": "up",
            "sparkline": [0, 1, 2, 3, 5, 6]
        }
    }
    """
    campaings = PlatformCampaign.objects.all()
    last_month_campaigns = get_last_month_objects_count(campaings)
    second_last_month_campaigns = get_second_last_month_objects_count(campaings)
    campaign_info_percentage = get_percentage(last_month_campaigns, second_last_month_campaigns)
    now = timezone.now()
    sparkline = []
    for i in range(5, -1, -1):
        start_date = now - timedelta(days=(i + 1) * 7)
        end_date = now - timedelta(days=i * 7)
        count = campaings.filter(created_at__gte=start_date, created_at__lte=end_date).count()
        sparkline.append(count)

    if last_month_campaigns > second_last_month_campaigns:
        direction = "up"
    elif last_month_campaigns < second_last_month_campaigns:
        direction = "down"
    else:
        direction = "neutral"

    return {
        "value": campaings.count(),
        "last_month": last_month_campaigns,
        "percentage": campaign_info_percentage,
        "trend": {
            "direction": direction,
            "sparkline": sparkline
        }
    }

def get_chart_data():
    """
    Get the data for the chart in the admin dashboard.
    [
        { 'month': "Jan", 'users': 2000, 'revenue': 2400 },
        .....
    ]
    """
    now = timezone.now()
    current_year = now.year
    current_month = now.month

    chart_data = []

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
        month_end = month_start.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

        month_name = month_start.strftime('%b')

        # Total cumulative users up to the end of this month
        users_count = User.objects.filter(joined_at__lte=month_end).count()

        # Monthly revenue (sum of paid payments within this month)
        month_revenue = (
            Payment.objects.filter(
                status='paid',
                paid_at__gte=month_start,
                paid_at__lte=month_end,
            )
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        chart_data.append({
            'month': month_name,
            'users': users_count,
            'revenue': float(month_revenue)
        })

    return chart_data

def get_camaigns_count_by_platform():
    """
    Get the count of campaigns by platform for the admin dashboard.

    """

    campaings = PlatformCampaign.objects.all()
    meta_campaigns = campaings.filter(integration__platform='META').count()
    google_campaigns = campaings.filter(integration__platform='GOOGLE').count()
    tiktok_campaigns = campaings.filter(integration__platform='TIKTOK').count()
    return {
        'meta': meta_campaigns,
        'google': google_campaigns,
        'tiktok': tiktok_campaigns
    }

def get_revenue_card_data():

    # Make revenue dynamic
    now = timezone.now()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = current_month_start
    last_month_start = (current_month_start - timedelta(days=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    monthly_revenue = (
        Payment.objects.filter(status='paid', paid_at__gte=current_month_start)
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )

    last_month_revenue = (
        Payment.objects.filter(
            status='paid',
            paid_at__gte=last_month_start,
            paid_at__lt=last_month_end,
        )
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0')
    )

    if last_month_revenue == 0:
        mrr_growth = 100.0 if monthly_revenue > 0 else 0.0
    else:
        mrr_growth = round(
            float((monthly_revenue - last_month_revenue) / last_month_revenue * 100), 2
        )
    current_year = now.year
    current_month = now.month
    sparkline = []

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
        month_end = month_start.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)

        # Monthly revenue (sum of paid payments within this month)
        month_revenue = (
            Payment.objects.filter(
                status='paid',
                paid_at__gte=month_start,
                paid_at__lte=month_end,
            )
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )
        sparkline.append(float(month_revenue))

    if mrr_growth > 0:
        direction = "up"
    elif mrr_growth < 0:
        direction = "down"
    else:
        direction = "neutral"

    return {
        'value': float(monthly_revenue),
        'percentage': mrr_growth,
        "trend": {
            "direction": direction,
            "sparkline": sparkline
        }
    }

def get_system_status():
    return {
        "api": { "status": "operational", "uptime_percent": 100.0 },
        "database": { "status": "operational", "uptime_percent": 100.0 }
    }
