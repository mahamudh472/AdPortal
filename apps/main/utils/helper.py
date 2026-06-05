import json
from django.db.models import Sum, F, FloatField, ExpressionWrapper
from django.utils import timezone
from datetime import timedelta
from apps.main.models import Organization, Platform, UnifiedCampaign
from apps.analysis.models import AnalysisDaily
from typing import Optional, Union

def preprocess_multipart_data(data, list_fields=None):
    """
    Standardize data from multipart/form-data (QueryDict) or standard dicts.
    Flattens single-value lists and parses JSON-encoded strings for list fields.
    """
    if list_fields is None:
        list_fields = {'platforms', 'locations', 'budgets'}
        
    # Use dict() instead of data.copy() to avoid QueryDict.__deepcopy__ issues with files
    data = dict(data.lists()) if hasattr(data, 'lists') else data.copy()
    
    # Flatten single-value lists from QueryDict, except list fields
    processed_data = {
        k: v if k in list_fields else (v[0] if isinstance(v, list) and len(v) == 1 else v)
        for k, v in data.items()
    }

    # Parse JSON-encoded strings for list fields (multipart/form-data)
    for field_name in list_fields:
        value = processed_data.get(field_name)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            try:
                parsed = json.loads(value[0])
                if isinstance(parsed, list):
                    processed_data[field_name] = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    processed_data[field_name] = parsed
            except (json.JSONDecodeError, TypeError):
                pass

    return processed_data


def get_performance_matrics(analysis_data):

    aggregates = analysis_data.aggregate(
        total_impressions=Sum('impressions'),
        total_clicks=Sum('clicks'),
        total_conversions=Sum('conversions'),
        total_spend=Sum('spend'),
        total_weighted_roas=Sum(
            ExpressionWrapper(F('roas') * F('spend'), output_field=FloatField())
        )
    )

    impressions = aggregates['total_impressions'] or 0
    clicks = aggregates['total_clicks'] or 0
    conversions = aggregates['total_conversions'] or 0
    spend = aggregates['total_spend'] or 0
    weighted_roas_sum = aggregates['total_weighted_roas'] or 0

    ctr = (clicks / impressions * 100) if impressions > 0 else 0
    cpc = (spend / clicks) if clicks > 0 else 0
    cpm = (spend / (impressions / 1000)) if impressions > 0 else 0
    cpa = (spend / conversions) if conversions > 0 else 0
    roas = (weighted_roas_sum / spend) if spend > 0 else 0

    return {
        'impressions': impressions,
        'clicks': clicks,
        'ctr': ctr,
        'conversions': conversions,
        'roas': roas,
        'cpc': cpc,
        'cpm': cpm,
        'cpa': cpa,
    }    



def get_dashboard_data(organization_id: str):
    organization = Organization.objects.get(snowflake_id=organization_id)
    # Required fieklds: total spend, impressions, click rate, roas
    # Required for matrics: Sepend overview(Meta, Google, TikTok), AI Insigts list, Recent campaigns list.
    
    six_moths_ago = timezone.now() - timedelta(days=180)
    analysis_data = AnalysisDaily.objects.filter(
        organization=organization,
        date__gte=six_moths_ago
    ).annotate(
        total_spend=Sum('spend'),
        ).order_by('platform')
    platforms = Platform.choices
    platform_values = [platform[0] for platform in platforms]

    result = {}
    months = []
    current_date = timezone.now().date()
    for i in range(5, -1, -1):
        month = (current_date - timedelta(days=i*30)).strftime('%b')
        months.append(month)
    for month in months:
        result[month] = {platform: 0 for platform in platform_values}

    for item in analysis_data:
        month = item.date.strftime('%b')
        if month in result:
            result[month][item.platform] += item.total_spend
    # TODO: Implement the logic to calculate total spend, impressions, click rate, and ROAS based on the organization's campaigns and ad data.
    all_analysis_data = AnalysisDaily.objects.filter(organization=organization)
    total_spend = all_analysis_data.aggregate(total_spend=Sum('spend'))['total_spend'] or 0
    impressions = all_analysis_data.aggregate(total_impressions=Sum('impressions'))['total_impressions'] or 0
    click_rate = (all_analysis_data.aggregate(total_clicks=Sum('clicks'))['total_clicks'] or 0) / impressions if impressions > 0 else 0
    roas = (all_analysis_data.aggregate(avg_roas=Sum('roas'))['avg_roas'] or 0) / all_analysis_data.count() if all_analysis_data.exists() else 0
    
    recent_campaigns = UnifiedCampaign.objects.filter(organization=organization).order_by('-created_at')[:5]
    from apps.main.serializers import AIInsightSerializer, SimpleCampaignSerializer
    ai_insights = AIInsightSerializer(organization.ai_insights.order_by('-created_at')[:5], many=True).data
    
    return {
        'total_spend': total_spend,
        'impressions': impressions,
        'click_rate': click_rate,
        'roas': roas,
        'spend_overview': result,
        'ai_insights': ai_insights,  
        'recent_campaigns': SimpleCampaignSerializer(recent_campaigns, many=True).data
    }

def get_analytics_data(organization_id: str):
    """
    Returns analytics data for the given organization:
    - top_metrics: Total spend, impressions, click_rate, conversions for the
      current calendar month plus % change vs the previous month.
    - monthly_performance: Last 6 months matrix of clicks, conversions, impressions.
    - spend_by_platform: Last 6 months monthly spend broken down by platform.
    - device_performance: Aggregated clicks and impressions by device type drawn
      from the device_breakdown JSONField.
    """
    from dateutil.relativedelta import relativedelta
    from apps.main.models import Platform

    organization = Organization.objects.get(snowflake_id=organization_id)
    today = timezone.now().date()

    # ── Calendar-month boundaries ──────────────────────────────────────────
    current_month_start = today.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    six_months_ago_start = current_month_start - relativedelta(months=5)

    all_data = AnalysisDaily.objects.filter(organization=organization)

    # ── Current & previous month aggregates ──────────────────────────────
    def _agg(qs):
        return qs.aggregate(
            spend=Sum('spend'),
            impressions=Sum('impressions'),
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
        )

    curr = _agg(all_data.filter(date__gte=current_month_start, date__lte=today))
    prev = _agg(all_data.filter(date__gte=prev_month_start, date__lte=prev_month_end))

    def _pct_change(current_val, prev_val):
        current_val = current_val or 0
        prev_val = prev_val or 0
        if prev_val == 0:
            return 100.0 if current_val > 0 else 0.0
        return round((current_val - prev_val) / prev_val * 100, 2)

    curr_impressions = curr['impressions'] or 0
    curr_clicks = curr['clicks'] or 0
    prev_impressions = prev['impressions'] or 0
    prev_clicks = prev['clicks'] or 0

    curr_ctr = (curr_clicks / curr_impressions * 100) if curr_impressions > 0 else 0.0
    prev_ctr = (prev_clicks / prev_impressions * 100) if prev_impressions > 0 else 0.0

    top_metrics = {
        'total_spend': {
            'value': round(curr['spend'] or 0, 2),
            'change_percent': _pct_change(curr['spend'], prev['spend']),
        },
        'impressions': {
            'value': curr_impressions,
            'change_percent': _pct_change(curr_impressions, prev_impressions),
        },
        'click_rate': {
            'value': round(curr_ctr, 2),
            'change_percent': _pct_change(curr_ctr, prev_ctr),
        },
        'conversions': {
            'value': curr['conversions'] or 0,
            'change_percent': _pct_change(curr['conversions'], prev['conversions']),
        },
    }

    # ── Last 6 months list (oldest → newest) ─────────────────────────────
    months_list = []
    for i in range(5, -1, -1):
        d = current_month_start - relativedelta(months=i)
        months_list.append((d.year, d.month, d.strftime('%b')))

    # ── Monthly performance matrix ────────────────────────────────────────
    monthly_performance = {label: {'clicks': 0, 'conversions': 0, 'impressions': 0} for _, _, label in months_list}

    for row in (
        all_data
        .filter(date__gte=six_months_ago_start, date__lte=today)
        .values('date__year', 'date__month')
        .annotate(
            total_clicks=Sum('clicks'),
            total_impressions=Sum('impressions'),
            total_conversions=Sum('conversions'),
        )
    ):
        for year, month, label in months_list:
            if row['date__year'] == year and row['date__month'] == month:
                monthly_performance[label]['clicks'] += row['total_clicks'] or 0
                monthly_performance[label]['impressions'] += row['total_impressions'] or 0
                monthly_performance[label]['conversions'] += row['total_conversions'] or 0

    # ── Spend by platform (current month total per platform) ─────────────
    platforms = [p[0] for p in Platform.choices]
    spend_by_platform = {p: 0.0 for p in platforms}

    for row in (
        all_data
        .filter(date__gte=current_month_start, date__lte=today)
        .values('platform')
        .annotate(total_spend=Sum('spend'))
    ):
        p = row['platform']
        if p in spend_by_platform:
            spend_by_platform[p] = round(row['total_spend'] or 0, 2)

    # ── Performance by device ─────────────────────────────────────────────
    # device_breakdown is stored as {"mobile": {"clicks": N, "impressions": M}, ...}
    device_performance: dict = {}
    for row in (
        all_data
        .filter(date__gte=six_months_ago_start, date__lte=today)
        .exclude(device_breakdown__isnull=True)
        .values_list('device_breakdown', flat=True)
    ):
        if not isinstance(row, dict):
            continue
        for device, metrics in row.items():
            if not isinstance(metrics, dict):
                continue
            bucket = device_performance.setdefault(device, {'clicks': 0, 'impressions': 0})
            bucket['clicks'] += metrics.get('clicks', 0) or 0
            bucket['impressions'] += metrics.get('impressions', 0) or 0

    return {
        'top_metrics': top_metrics,
        'monthly_performance': monthly_performance,
        'spend_by_platform': spend_by_platform,
        'device_performance': device_performance,
    }

