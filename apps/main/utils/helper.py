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



CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'INR': '₹', 'BDT': '৳',
    'CAD': 'C$', 'AUD': 'A$', 'JPY': '¥', 'BRL': 'R$', 'MXN': 'MX$',
}


def format_money(amount, currency):
    """Format an amount without silently pretending every account is USD."""
    amount = float(amount or 0.0)
    currency = (currency or 'USD').upper()
    symbol = CURRENCY_SYMBOLS.get(currency)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{currency} {amount:,.2f}"


def _pct_change(current_value, previous_value):
    """Percentage change, or ``None`` when the previous period is empty.

    ``None`` means "new" / "not comparable"; the frontend renders it as "-"
    instead of a made-up +100%.
    """
    current_value = float(current_value or 0.0)
    previous_value = float(previous_value or 0.0)
    if previous_value == 0:
        return None
    return round((current_value - previous_value) / previous_value * 100.0, 1)


def _delta_fields(change_percent, *, lower_is_better=False):
    if change_percent is None:
        return {'delta': '—', 'change_percent': None, 'is_positive': None}
    positive = change_percent <= 0 if lower_is_better else change_percent >= 0
    arrow = '↑' if change_percent >= 0 else '↓'
    return {
        'delta': f"{arrow} {abs(change_percent):.1f}%",
        'change_percent': change_percent,
        'is_positive': positive,
    }


def _bucket_series(start, end):
    """Bucket definitions covering every day in [start, end] without gaps."""
    total_days = max(1, (end - start).days + 1)
    if total_days <= 31:
        return [
            {'start': start + timedelta(days=i), 'end': start + timedelta(days=i),
             'key': (start + timedelta(days=i)).isoformat(),
             'label': (start + timedelta(days=i)).strftime('%b %d')}
            for i in range(total_days)
        ]
    if total_days <= 120:
        buckets = []
        for offset in range(0, total_days, 7):
            bucket_start = start + timedelta(days=offset)
            bucket_end = min(end, bucket_start + timedelta(days=6))
            buckets.append({
                'start': bucket_start, 'end': bucket_end,
                'key': bucket_start.isoformat(),
                'label': bucket_start.strftime('%b %d'),
            })
        return buckets

    buckets = []
    cursor = start.replace(day=1)
    while cursor <= end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        bucket_end = min(end, next_month - timedelta(days=1))
        buckets.append({
            'start': max(start, cursor), 'end': bucket_end,
            'key': cursor.strftime('%Y-%m'),
            'label': cursor.strftime('%b %y') if total_days > 365 else cursor.strftime('%b'),
        })
        cursor = next_month
    return buckets


def _bucket_key_for(day, buckets):
    for bucket in buckets:
        if bucket['start'] <= day <= bucket['end']:
            return bucket['key']
    return None


def _primary_currency(organization, analysis_qs, start, end):
    integrations = list(organization.integrations.filter(is_active=True))
    integration_currency = next(
        (i.currency.upper() for i in integrations if i.currency), None
    )
    by_currency = {
        (row['currency'] or '').upper(): float(row['spend'] or 0)
        for row in analysis_qs.filter(date__gte=start, date__lte=end)
        .values('currency').annotate(spend=Sum('spend'))
    }
    non_blank = {c: v for c, v in by_currency.items() if c}
    if integration_currency and (integration_currency in non_blank or not non_blank):
        return integration_currency, by_currency, len(non_blank) > 1
    if non_blank:
        top = max(non_blank, key=non_blank.get)
        return top, by_currency, len(non_blank) > 1
    return 'USD', by_currency, False


def get_dashboard_data(
    organization_id: str,
    time_range: str = 'last_30_days',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Dashboard payload computed only from stored analytics.

    No demo rows are ever returned: an organization without data gets zeroed
    cards, empty campaign/insight lists and ``has_data=False`` so the frontend
    can show a connect-your-accounts state.
    """
    from datetime import datetime
    from django.db.models import Max, Min
    from apps.analysis.models import AnalysisBreakdownDaily
    from apps.main.serializers import SimpleCampaignSerializer
    from apps.main.services.campaign import CampaignService
    from apps.main.services.optimization import (
        ICON_BY_TYPE, build_budget_recommendation, extract_roi_impact,
    )

    organization = Organization.objects.get(snowflake_id=organization_id)
    today = timezone.now().date()
    all_analysis = AnalysisDaily.objects.filter(organization=organization)

    # ── 1. Date range & comparison period ─────────────────────────────────────
    curr_start = curr_end = None
    if start_date and end_date:
        try:
            curr_start = datetime.strptime(start_date, '%Y-%m-%d').date()
            curr_end = datetime.strptime(end_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            curr_start, curr_end = None, None

    if not curr_start or not curr_end:
        if time_range == 'last_7_days':
            curr_end = today
            curr_start = today - timedelta(days=6)
        elif time_range == 'this_month':
            curr_start = today.replace(day=1)
            curr_end = today
        elif time_range == 'last_month':
            curr_end = today.replace(day=1) - timedelta(days=1)
            curr_start = curr_end.replace(day=1)
        elif time_range == 'all_time':
            curr_end = today
            first_date = all_analysis.aggregate(first=Min('date'))['first']
            curr_start = first_date or today
        else:
            curr_end = today
            curr_start = today - timedelta(days=29)

    period_days = max(1, (curr_end - curr_start).days + 1)
    prev_end = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)

    date_label = f"{curr_start.strftime('%b %d')} – {curr_end.strftime('%b %d, %Y')}"
    comparison_label = f"vs {prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d')}"

    currency, currency_totals, mixed_currencies = _primary_currency(
        organization, all_analysis, curr_start, curr_end
    )
    currency_key = currency or 'USD'

    def scoped(qs):
        return qs.filter(currency__in=['', currency_key])

    curr_qs = scoped(all_analysis.filter(date__gte=curr_start, date__lte=curr_end))
    prev_qs = scoped(all_analysis.filter(date__gte=prev_start, date__lte=prev_end))
    has_any_data = all_analysis.exists()
    period_has_data = curr_qs.exists()

    def aggregate(qs):
        return qs.aggregate(
            spend=Sum('spend'),
            impressions=Sum('impressions'),
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
            conversion_value=Sum('conversion_value'),
        )

    curr_agg = aggregate(curr_qs)
    prev_agg = aggregate(prev_qs)
    curr_spend = float(curr_agg['spend'] or 0.0)
    prev_spend = float(prev_agg['spend'] or 0.0)
    curr_imp = int(curr_agg['impressions'] or 0)
    prev_imp = int(prev_agg['impressions'] or 0)
    curr_clk = int(curr_agg['clicks'] or 0)
    prev_clk = int(prev_agg['clicks'] or 0)
    curr_conv = float(curr_agg['conversions'] or 0.0)
    prev_conv = float(prev_agg['conversions'] or 0.0)
    curr_value = float(curr_agg['conversion_value'] or 0.0)
    prev_value = float(prev_agg['conversion_value'] or 0.0)
    curr_roas = round(_safe_div(curr_value, curr_spend), 2)
    prev_roas = round(_safe_div(prev_value, prev_spend), 2)
    curr_cpa = round(_safe_div(curr_spend, curr_conv), 2)
    prev_cpa = round(_safe_div(prev_spend, prev_conv), 2)
    curr_ctr = round(_safe_div(curr_clk, curr_imp, 100.0), 2)
    prev_ctr = round(_safe_div(prev_clk, prev_imp, 100.0), 2)

    # ── 2. Buckets, per-platform totals and sparklines ────────────────────────
    buckets = _bucket_series(curr_start, curr_end)
    bucket_template = {
        b['key']: {
            'spend': 0.0, 'impressions': 0, 'clicks': 0, 'conversions': 0.0,
            'conversion_value': 0.0,
        }
        for b in buckets
    }
    platform_buckets = {
        'META': {k: dict(v) for k, v in bucket_template.items()},
        'GOOGLE': {k: dict(v) for k, v in bucket_template.items()},
        'TIKTOK': {k: dict(v) for k, v in bucket_template.items()},
        'TOTAL': {k: dict(v) for k, v in bucket_template.items()},
    }

    platform_curr = {}
    platform_prev = {
        row['platform']: float(row['spend'] or 0.0)
        for row in prev_qs.values('platform').annotate(spend=Sum('spend'))
    }
    for row in curr_qs.values('date', 'platform').annotate(
        spend=Sum('spend'), impressions=Sum('impressions'),
        clicks=Sum('clicks'), conversions=Sum('conversions'),
        conversion_value=Sum('conversion_value'),
    ):
        platform = row['platform']
        vals = {
            'spend': float(row['spend'] or 0.0),
            'impressions': int(row['impressions'] or 0),
            'clicks': int(row['clicks'] or 0),
            'conversions': float(row['conversions'] or 0.0),
            'conversion_value': float(row['conversion_value'] or 0.0),
        }
        platform_curr[platform] = platform_curr.get(platform, 0.0) + vals['spend']
        key = _bucket_key_for(row['date'], buckets)
        for target in (platform, 'TOTAL'):
            if target in platform_buckets and key in platform_buckets[target]:
                for field, value in vals.items():
                    platform_buckets[target][key][field] += value

    # Meta's publisher-platform breakdown gives the real Facebook/Instagram split.
    publisher_rows = list(
        AnalysisBreakdownDaily.objects
        .filter(organization=organization, dimension='publisher_platform',
                date__gte=curr_start, date__lte=curr_end,
                currency__in=['', currency_key])
        .values('date', 'key')
        .annotate(spend=Sum('spend'), impressions=Sum('impressions'),
                  clicks=Sum('clicks'), conversions=Sum('conversions'),
                  conversion_value=Sum('conversion_value'))
    )
    previous_publisher_spend = {'facebook': 0.0, 'instagram': 0.0}
    for row in (
        AnalysisBreakdownDaily.objects
        .filter(organization=organization, dimension='publisher_platform',
                date__gte=prev_start, date__lte=prev_end,
                currency__in=['', currency_key])
        .values('key').annotate(spend=Sum('spend'))
    ):
        key = (row['key'] or '').lower()
        if key in previous_publisher_spend:
            previous_publisher_spend[key] = float(row['spend'] or 0.0)

    publisher_daily = {}
    has_publisher_split = False
    for row in publisher_rows:
        key = (row['key'] or '').lower()
        if key not in ('facebook', 'instagram'):
            continue
        has_publisher_split = True
        bucket_key = _bucket_key_for(row['date'], buckets)
        if bucket_key is None:
            continue
        publisher_daily.setdefault(key, {k: dict(v) for k, v in bucket_template.items()})
        destination = publisher_daily[key][bucket_key]
        destination['spend'] += float(row['spend'] or 0.0)
        destination['impressions'] += int(row['impressions'] or 0)
        destination['clicks'] += int(row['clicks'] or 0)
        destination['conversions'] += float(row['conversions'] or 0.0)
        destination['conversion_value'] += float(row['conversion_value'] or 0.0)

    meta_curr = platform_curr.get(Platform.META, 0.0)
    meta_prev = platform_prev.get(Platform.META, 0.0)
    if has_publisher_split:
        fb_curr = sum(b['spend'] for b in publisher_daily.get('facebook', {}).values())
        ig_curr = sum(b['spend'] for b in publisher_daily.get('instagram', {}).values())
        fb_prev = previous_publisher_spend['facebook']
        ig_prev = previous_publisher_spend['instagram']
        fb_buckets = publisher_daily.get('facebook', bucket_template)
        ig_buckets = publisher_daily.get('instagram', bucket_template)
    else:
        # No breakdown yet: attribute Meta spend to Facebook and leave Instagram at
        # zero rather than inventing a 77/23 split.
        fb_curr, ig_curr = meta_curr, 0.0
        fb_prev, ig_prev = meta_prev, 0.0
        fb_buckets = platform_buckets['META']
        ig_buckets = {k: dict(v) for k, v in bucket_template.items()}

    goog_curr = platform_curr.get(Platform.GOOGLE, 0.0)
    goog_prev = platform_prev.get(Platform.GOOGLE, 0.0)
    tt_curr = platform_curr.get(Platform.TIKTOK, 0.0)
    tt_prev = platform_prev.get(Platform.TIKTOK, 0.0)
    total_curr = curr_spend
    total_prev = prev_spend

    def sparkline(bucket_values, field='spend'):
        return [round(bucket_values[b['key']][field], 2) for b in buckets
                if b['key'] in bucket_values]

    cards = [
        ('Facebook', 'facebook', fb_curr, fb_prev, fb_buckets, '#2563eb'),
        ('Google Ads', 'google', goog_curr, goog_prev, platform_buckets['GOOGLE'], '#10b981'),
        ('TikTok', 'tiktok', tt_curr, tt_prev, platform_buckets['TIKTOK'], '#1e293b'),
        ('Instagram', 'instagram', ig_curr, ig_prev, ig_buckets, '#ec4899'),
        ('Total Spend', 'total', total_curr, total_prev, platform_buckets['TOTAL'], '#2563eb'),
    ]
    platform_cards = []
    for name, key, spend, prev, bucket_values, color in cards:
        change = _pct_change(spend, prev)
        card = {
            'name': name,
            'platform': key,
            'spend': round(spend, 2),
            'formatted_spend': format_money(spend, currency_key),
            'sub_label': comparison_label,
            'color': color,
            'sparkline': sparkline(bucket_values),
            **_delta_fields(change),
        }
        if key in ('facebook', 'instagram') and not has_publisher_split and spend:
            card['estimated'] = True
        platform_cards.append(card)

    # ── 3. Overview metrics ───────────────────────────────────────────────────
    def _fmt_num(n):
        if n >= 1_000_000:
            return f"{(n / 1_000_000):.2f}M"
        if n >= 1_000:
            return f"{(n / 1_000):.0f}K"
        return str(n)

    overview_metrics = [
        {
            'id': 'impressions', 'label': 'Impressions', 'value': _fmt_num(curr_imp),
            'raw_value': curr_imp, **_delta_fields(_pct_change(curr_imp, prev_imp)),
        },
        {
            'id': 'clicks', 'label': 'Clicks', 'value': _fmt_num(curr_clk),
            'raw_value': curr_clk, **_delta_fields(_pct_change(curr_clk, prev_clk)),
        },
        {
            'id': 'conversions', 'label': 'Conversions', 'value': f"{curr_conv:,.0f}",
            'raw_value': curr_conv, **_delta_fields(_pct_change(curr_conv, prev_conv)),
        },
        {
            'id': 'cost_per_conversion', 'label': 'Cost / Conv.',
            'value': format_money(curr_cpa, currency_key), 'raw_value': curr_cpa,
            **_delta_fields(_pct_change(curr_cpa, prev_cpa), lower_is_better=True),
        },
        {
            'id': 'roas', 'label': 'ROAS', 'value': f"{curr_roas:.2f}x",
            'raw_value': curr_roas, **_delta_fields(_pct_change(curr_roas, prev_roas)),
        },
    ]

    # ── 4. Chart data (every bucket, no gaps) ─────────────────────────────────
    chart_data = []
    for bucket in buckets:
        key = bucket['key']
        chart_data.append({
            'date': bucket['label'],
            'Facebook': round(fb_buckets.get(key, {}).get('spend', 0.0), 1),
            'GoogleAds': round(platform_buckets['GOOGLE'].get(key, {}).get('spend', 0.0), 1),
            'TikTok': round(platform_buckets['TIKTOK'].get(key, {}).get('spend', 0.0), 1),
            'Instagram': round(ig_buckets.get(key, {}).get('spend', 0.0), 1),
        })

    # ── 5. Top campaigns (real only) ─────────────────────────────────────────
    campaigns_qs = UnifiedCampaign.objects.filter(organization=organization)
    campaigns_qs = CampaignService().annotate_queryset_with_metrics(campaigns_qs)
    top_camps = (
        campaigns_qs.prefetch_related('platform_campaigns__integration')
        .order_by('-_total_spent', '-created_at')[:5]
    )
    top_campaigns = []
    for c in top_camps:
        c_spend = getattr(c, '_total_spent', 0.0) or 0.0
        c_conv = getattr(c, '_conversions', 0) or 0
        c_w_roas = getattr(c, '_weighted_roas', 0.0) or 0.0
        c_roas = round(c_w_roas / c_spend, 2) if c_spend > 0 else 0.0
        c_imp = getattr(c, '_impressions', 0) or 0
        c_clk = getattr(c, '_clicks', 0) or 0
        c_ctr = round(c_clk / c_imp * 100, 2) if c_imp > 0 else 0.0
        platforms = (
            [pc.integration.platform for pc in c.platform_campaigns.all()]
            if c.status != 'DRAFT'
            else ((c.draft_data or {}).get('platforms') or [])
        )
        primary = platforms[0] if platforms else 'META'
        platform_name = {'META': 'Facebook', 'GOOGLE': 'Google Ads', 'TIKTOK': 'TikTok'}.get(
            primary, primary
        )
        top_campaigns.append({
            'id': c.id,
            'name': c.name,
            'platform': platform_name,
            'platforms': platforms,
            'spend': format_money(c_spend, c.currency or currency_key),
            'raw_spend': c_spend,
            'conversions': f"{c_conv:,.0f}",
            'raw_conversions': c_conv,
            'roas': f"{c_roas:.2f}x",
            'raw_roas': c_roas,
            'ctr': f"{c_ctr:.2f}%",
            'raw_ctr': c_ctr,
            'status': c.status,
        })

    # ── 6. AI insights (stored values only) ──────────────────────────────────
    db_insights = list(
        organization.ai_insights.filter(status='OPEN').order_by('-created_at')[:12]
    )
    db_insights.sort(
        key=lambda i: ({'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}.get(i.impact, 0), i.created_at),
        reverse=True,
    )
    ai_insights = []
    for ins in db_insights[:3]:
        confidence = ins.confidence or 0
        impact_badge = (
            'High Impact' if ins.impact == 'HIGH'
            else ('Medium Impact' if ins.impact == 'MEDIUM' else 'Tip')
        )
        ai_insights.append({
            'id': ins.id,
            'title': ins.title,
            'description': ins.description,
            'impact': ins.impact,
            'impact_badge': impact_badge,
            'confidence': confidence,
            'confidence_text': f"Confidence: {confidence}%" if ins.confidence is not None else 'Confidence: —',
            'roi_impact': extract_roi_impact(ins),
            'icon_type': ICON_BY_TYPE.get(ins.recommendation_type, 'bar'),
            'recommendation_type': ins.recommendation_type,
            'created_at': ins.created_at.isoformat(),
        })

    # ── 7. Budget recommendation ─────────────────────────────────────────────
    budget_recommendation = build_budget_recommendation(organization)

    # ── 8. Legacy fields, now real calendar months ───────────────────────────
    current_month = today.replace(day=1)
    month_starts = []
    for i in range(5, -1, -1):
        year = current_month.year
        month = current_month.month - i
        while month <= 0:
            month += 12
            year -= 1
        month_starts.append((year, month))
    month_labels = {
        (year, month): datetime(year, month, 1).strftime('%b')
        for year, month in month_starts
    }
    result_overview = {label: {p: 0.0 for p in Platform.values} for label in month_labels.values()}
    six_months_start = datetime(month_starts[0][0], month_starts[0][1], 1).date()
    for row in (
        scoped(all_analysis)
        .filter(date__gte=six_months_start, date__lte=today)
        .values('date__year', 'date__month', 'platform')
        .annotate(spend=Sum('spend'))
    ):
        label = month_labels.get((row['date__year'], row['date__month']))
        if label and row['platform'] in result_overview[label]:
            result_overview[label][row['platform']] = round(row['spend'] or 0, 2)

    recent_campaigns = UnifiedCampaign.objects.filter(
        organization=organization
    ).order_by('-created_at')[:5]

    last_synced_at = (
        organization.integrations.filter(is_active=True)
        .aggregate(latest=Max('analytics_synced_at'))['latest']
        or all_analysis.aggregate(latest=Max('synced_at'))['latest']
    )
    partial_platforms = []
    for integration in organization.integrations.filter(is_active=True):
        if integration.analytics_synced_at is None:
            partial_platforms.append({'platform': integration.platform, 'reason': 'not_synced'})
        elif integration.analytics_error:
            partial_platforms.append({
                'platform': integration.platform,
                'reason': 'error',
                'error': integration.analytics_error,
            })

    return {
        'date_range': {
            'selected': time_range,
            'label': date_label,
            'comparison_label': comparison_label,
            'start_date': curr_start.isoformat(),
            'end_date': curr_end.isoformat(),
        },
        'has_data': has_any_data,
        'has_period_data': period_has_data,
        'last_synced_at': last_synced_at.isoformat() if last_synced_at else None,
        'partial_platforms': partial_platforms,
        'currency': currency_key,
        'mixed_currencies': mixed_currencies,
        'currency_totals': {
            (key or currency_key): round(value, 2)
            for key, value in currency_totals.items()
        },
        'platform_cards': platform_cards,
        'overview_metrics': overview_metrics,
        'chart_data': chart_data,
        'top_campaigns': top_campaigns,
        'ai_insights': ai_insights,
        'budget_recommendation': budget_recommendation,
        'total_spend': round(curr_spend, 2),
        'impressions': curr_imp,
        'click_rate': curr_ctr,
        'roas': curr_roas,
        'spend_overview': result_overview,
        'recent_campaigns': SimpleCampaignSerializer(recent_campaigns, many=True).data,
    }


def _safe_div(numerator, denominator, scale=1.0):
    return (float(numerator or 0) / float(denominator) * scale) if denominator else 0.0


def get_analytics_data(organization_id: str, chart_range: str = '6M'):
    """
    Analytics payload for the selected range, entirely from stored analytics.

    ``device_performance`` prefers ``AnalysisBreakdownDaily`` (new ingestion) and
    falls back to the legacy ``device_breakdown`` JSON for old rows. ``breakdowns``
    exposes every dimension (publisher platform, placement, device, hour, age,
    gender, country) so new charts need no extra endpoint.
    """
    from dateutil.relativedelta import relativedelta
    from django.db.models import Max
    from apps.analysis.models import AnalysisBreakdownDaily
    from apps.main.models import Platform
    from apps.main.utils.user_pages import build_platform_insights

    organization = Organization.objects.get(snowflake_id=organization_id)
    today = timezone.now().date()

    current_month_start = today.replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    six_months_ago_start = current_month_start - relativedelta(months=5)

    all_data = AnalysisDaily.objects.filter(organization=organization)
    has_any_data = all_data.exists()
    currency, currency_totals, mixed_currencies = _primary_currency(
        organization, all_data, six_months_ago_start, today
    )
    currency_key = currency or 'USD'
    all_data = all_data.filter(currency__in=['', currency_key])

    def aggregate(qs):
        return qs.aggregate(
            spend=Sum('spend'), impressions=Sum('impressions'),
            clicks=Sum('clicks'), conversions=Sum('conversions'),
            conversion_value=Sum('conversion_value'),
        )

    curr = aggregate(all_data.filter(date__gte=current_month_start, date__lte=today))
    prev = aggregate(all_data.filter(date__gte=prev_month_start, date__lte=prev_month_end))

    curr_impressions = int(curr['impressions'] or 0)
    curr_clicks = int(curr['clicks'] or 0)
    prev_impressions = int(prev['impressions'] or 0)
    prev_clicks = int(prev['clicks'] or 0)
    curr_ctr = _safe_div(curr_clicks, curr_impressions, 100)
    prev_ctr = _safe_div(prev_clicks, prev_impressions, 100)

    top_metrics = {
        'total_spend': {
            'value': round(curr['spend'] or 0, 2),
            'formatted_value': format_money(curr['spend'] or 0, currency_key),
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

    # ── Performance series ───────────────────────────────────────────────────
    chart_range = (chart_range or '6M').upper()
    monthly_performance = {}
    sparkline_months = [
        (current_month_start - relativedelta(months=i)) for i in range(5, -1, -1)
    ]

    if chart_range in ('7D', '30D'):
        span = 7 if chart_range == '7D' else 30
        first_day = today - timedelta(days=span - 1)
        days = [first_day + timedelta(days=i) for i in range(span)]
        monthly_performance = {
            d.strftime('%b %d'): {'clicks': 0, 'conversions': 0, 'impressions': 0}
            for d in days
        }
        for row in (
            all_data.filter(date__gte=first_day, date__lte=today)
            .values('date')
            .annotate(
                total_clicks=Sum('clicks'), total_impressions=Sum('impressions'),
                total_conversions=Sum('conversions'),
            )
        ):
            bucket = monthly_performance[row['date'].strftime('%b %d')]
            bucket['clicks'] += row['total_clicks'] or 0
            bucket['impressions'] += row['total_impressions'] or 0
            bucket['conversions'] += row['total_conversions'] or 0
    else:
        month_count = {'3M': 3, '1Y': 12}.get(chart_range, 6)
        range_start = current_month_start - relativedelta(months=month_count - 1)
        months_list = []
        for i in range(month_count - 1, -1, -1):
            d = current_month_start - relativedelta(months=i)
            months_list.append((
                d.year, d.month,
                d.strftime('%b') if month_count <= 6 else d.strftime('%b %y'),
            ))
        monthly_performance = {
            label: {'clicks': 0, 'conversions': 0, 'impressions': 0}
            for _, _, label in months_list
        }
        by_month = {(year, month): label for year, month, label in months_list}
        for row in (
            all_data.filter(date__gte=range_start, date__lte=today)
            .values('date__year', 'date__month')
            .annotate(
                total_clicks=Sum('clicks'), total_impressions=Sum('impressions'),
                total_conversions=Sum('conversions'),
            )
        ):
            label = by_month.get((row['date__year'], row['date__month']))
            if label:
                monthly_performance[label]['clicks'] += row['total_clicks'] or 0
                monthly_performance[label]['impressions'] += row['total_impressions'] or 0
                monthly_performance[label]['conversions'] += row['total_conversions'] or 0

    spark = {
        k: {d.strftime('%Y-%m'): 0 for d in sparkline_months}
        for k in ('spend', 'impressions', 'clicks', 'conversions')
    }
    for row in (
        all_data.filter(date__gte=six_months_ago_start, date__lte=today)
        .values('date__year', 'date__month')
        .annotate(s=Sum('spend'), i=Sum('impressions'), c=Sum('clicks'), v=Sum('conversions'))
    ):
        key = f"{row['date__year']:04d}-{row['date__month']:02d}"
        if key in spark['spend']:
            spark['spend'][key] = round(row['s'] or 0, 2)
            spark['impressions'][key] = row['i'] or 0
            spark['clicks'][key] = row['c'] or 0
            spark['conversions'][key] = row['v'] or 0

    def sparkline(metric):
        return list(spark[metric].values())

    top_metrics['total_spend']['sparkline'] = sparkline('spend')
    top_metrics['impressions']['sparkline'] = sparkline('impressions')
    top_metrics['click_rate']['sparkline'] = [
        round((c / i * 100) if i else 0, 2)
        for c, i in zip(spark['clicks'].values(), spark['impressions'].values())
    ]
    top_metrics['conversions']['sparkline'] = sparkline('conversions')

    # ── Spend by platform / publisher platform ───────────────────────────────
    platforms = [p[0] for p in Platform.choices]
    spend_by_platform = {p: 0.0 for p in platforms}
    for row in (
        all_data.filter(date__gte=current_month_start, date__lte=today)
        .values('platform').annotate(total_spend=Sum('spend'))
    ):
        if row['platform'] in spend_by_platform:
            spend_by_platform[row['platform']] = round(row['total_spend'] or 0, 2)

    publisher_platform_spend = {}
    for row in (
        AnalysisBreakdownDaily.objects
        .filter(organization=organization, dimension='publisher_platform',
                date__gte=current_month_start, date__lte=today,
                currency__in=['', currency_key])
        .values('key').annotate(spend=Sum('spend'))
    ):
        key = (row['key'] or '').lower()
        if key:
            publisher_platform_spend[key] = round(row['spend'] or 0, 2)

    # ── Breakdowns (last six months) ─────────────────────────────────────────
    breakdowns = {}
    for dimension in AnalysisBreakdownDaily.Dimension.values:
        rows = (
            AnalysisBreakdownDaily.objects
            .filter(organization=organization, dimension=dimension,
                    date__gte=six_months_ago_start, date__lte=today,
                    currency__in=['', currency_key])
            .values('key')
            .annotate(
                impressions=Sum('impressions'), clicks=Sum('clicks'),
                spend=Sum('spend'), conversions=Sum('conversions'),
                conversion_value=Sum('conversion_value'),
            )
            .order_by('-spend')
        )
        breakdowns[dimension] = [
            {
                'key': row['key'],
                'impressions': int(row['impressions'] or 0),
                'clicks': int(row['clicks'] or 0),
                'spend': round(row['spend'] or 0, 2),
                'conversions': float(row['conversions'] or 0),
                'conversion_value': round(row['conversion_value'] or 0, 2),
            }
            for row in rows
        ]

    # Prefer the new device breakdown; fall back to the legacy JSON for old rows.
    device_performance = {}
    if breakdowns.get('device'):
        for row in breakdowns['device']:
            device_performance[row['key']] = {
                'clicks': row['clicks'],
                'impressions': row['impressions'],
                'spend': row['spend'],
                'conversions': row['conversions'],
            }
    else:
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
                bucket = device_performance.setdefault(
                    device, {'clicks': 0, 'impressions': 0, 'spend': 0.0, 'conversions': 0}
                )
                bucket['clicks'] += metrics.get('clicks', 0) or 0
                bucket['impressions'] += metrics.get('impressions', 0) or 0

    last_synced_at = (
        organization.integrations.filter(is_active=True)
        .aggregate(latest=Max('analytics_synced_at'))['latest']
        or all_data.aggregate(latest=Max('synced_at'))['latest']
    )

    return {
        'has_data': has_any_data,
        'last_synced_at': last_synced_at.isoformat() if last_synced_at else None,
        'currency': currency_key,
        'mixed_currencies': mixed_currencies,
        'currency_totals': {
            (key or currency_key): round(value, 2)
            for key, value in currency_totals.items()
        },
        'top_metrics': top_metrics,
        'monthly_performance': monthly_performance,
        'spend_by_platform': spend_by_platform,
        'publisher_platform_spend': publisher_platform_spend,
        'device_performance': device_performance,
        'breakdowns': breakdowns,
        'insights_summary': build_platform_insights(
            all_data.filter(date__gte=six_months_ago_start, date__lte=today)
        ),
    }
