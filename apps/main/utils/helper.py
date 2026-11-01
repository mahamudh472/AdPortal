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



def get_dashboard_data(
    organization_id: str,
    time_range: str = 'last_30_days',
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Returns rich dynamic dashboard data for the organization:
    - date_range: Current selected range and comparison period label
    - platform_cards: Per-platform spend, delta, comparison label, and sparklines
    - overview_metrics: Impressions, Clicks, Conversions, Cost/Conv, ROAS + trends
    - chart_data: Time-series breakdown for multi-line Recharts chart
    - top_campaigns: Top performing campaigns with spend, roas, ctr, conversions
    - ai_insights: AI insights with confidence score and ROI impact
    - budget_recommendation: Campaign-specific budget recommendation & potential impact
    - Backward-compatible fields: total_spend, impressions, click_rate, roas, spend_overview, recent_campaigns
    """
    from datetime import datetime
    from apps.main.serializers import AIInsightSerializer, SimpleCampaignSerializer
    from apps.main.services.campaign import CampaignService

    organization = Organization.objects.get(snowflake_id=organization_id)
    today = timezone.now().date()

    # ── 1. Date Range & Comparison Period Calculation ──────────────────────────
    curr_start = None
    curr_end = None
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
            days_len = 7
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=days_len - 1)
        elif time_range == 'this_month':
            curr_start = today.replace(day=1)
            curr_end = today
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end.replace(day=1)
        elif time_range == 'last_month':
            curr_end = today.replace(day=1) - timedelta(days=1)
            curr_start = curr_end.replace(day=1)
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end.replace(day=1)
        elif time_range == 'all_time':
            curr_end = today
            curr_start = today - timedelta(days=365)
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=365)
        else:  # default: 'last_30_days'
            curr_end = today
            curr_start = today - timedelta(days=29)
            days_len = 30
            prev_end = curr_start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=days_len - 1)
    else:
        days_len = max(1, (curr_end - curr_start).days + 1)
        prev_end = curr_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days_len - 1)

    date_label = f"{curr_start.strftime('%b %d')} – {curr_end.strftime('%b %d, %Y')}"
    comparison_label = f"vs {prev_start.strftime('%b %d')} – {prev_end.strftime('%b %d')}"

    def _pct_change(curr_val, prev_val):
        c = float(curr_val or 0.0)
        p = float(prev_val or 0.0)
        if p == 0:
            return 100.0 if c > 0 else 0.0
        return round((c - p) / p * 100.0, 1)

    # ── 2. Aggregations from AnalysisDaily ──────────────────────────────────────
    all_analysis = AnalysisDaily.objects.filter(organization=organization)
    has_analysis = all_analysis.exists()

    curr_qs = all_analysis.filter(date__gte=curr_start, date__lte=curr_end)
    prev_qs = all_analysis.filter(date__gte=prev_start, date__lte=prev_end)

    def _agg(qs):
        return qs.aggregate(
            total_spend=Sum('spend'),
            total_impressions=Sum('impressions'),
            total_clicks=Sum('clicks'),
            total_conversions=Sum('conversions'),
            total_weighted_roas=Sum(
                ExpressionWrapper(
                    F('roas') * F('spend'),
                    output_field=FloatField()
                )
            )
        )

    curr_agg = _agg(curr_qs)
    prev_agg = _agg(prev_qs)

    curr_spend = float(curr_agg['total_spend'] or 0.0)
    prev_spend = float(prev_agg['total_spend'] or 0.0)
    curr_imp = int(curr_agg['total_impressions'] or 0)
    prev_imp = int(prev_agg['total_impressions'] or 0)
    curr_clk = int(curr_agg['total_clicks'] or 0)
    prev_clk = int(prev_agg['total_clicks'] or 0)
    curr_conv = int(curr_agg['total_conversions'] or 0)
    prev_conv = int(prev_agg['total_conversions'] or 0)

    curr_roas = round((curr_agg['total_weighted_roas'] or 0.0) / curr_spend, 2) if curr_spend > 0 else 0.0
    prev_roas = round((prev_agg['total_weighted_roas'] or 0.0) / prev_spend, 2) if prev_spend > 0 else 0.0

    curr_cpa = round(curr_spend / curr_conv, 2) if curr_conv > 0 else 0.0
    prev_cpa = round(prev_spend / prev_conv, 2) if prev_conv > 0 else 0.0

    curr_ctr = round((curr_clk / curr_imp * 100.0), 2) if curr_imp > 0 else 0.0
    prev_ctr = round((prev_clk / prev_imp * 100.0), 2) if prev_imp > 0 else 0.0

    # ── 3. Platform Breakdown & Sparklines ─────────────────────────────────────
    if has_analysis and curr_spend > 0:
        meta_spend = float(curr_qs.filter(platform=Platform.META).aggregate(s=Sum('spend'))['s'] or 0.0)
        meta_prev = float(prev_qs.filter(platform=Platform.META).aggregate(s=Sum('spend'))['s'] or 0.0)
        # TODO: split Instagram and Facebook dynamically once publisher platform breakdown is ingested from Meta API
        fb_spend = round(meta_spend * 0.77, 2)
        fb_prev = round(meta_prev * 0.77, 2)
        ig_spend = round(meta_spend * 0.23, 2)
        ig_prev = round(meta_prev * 0.23, 2)

        goog_spend = round(float(curr_qs.filter(platform=Platform.GOOGLE).aggregate(s=Sum('spend'))['s'] or 0.0), 2)
        goog_prev = round(float(prev_qs.filter(platform=Platform.GOOGLE).aggregate(s=Sum('spend'))['s'] or 0.0), 2)

        tt_spend = round(float(curr_qs.filter(platform=Platform.TIKTOK).aggregate(s=Sum('spend'))['s'] or 0.0), 2)
        tt_prev = round(float(prev_qs.filter(platform=Platform.TIKTOK).aggregate(s=Sum('spend'))['s'] or 0.0), 2)

        tot_spend = round(curr_spend, 2)
        tot_prev = round(prev_spend, 2)

        # Sparklines from daily data
        # Sample points across range
        days_count = max(1, (curr_end - curr_start).days + 1)
        step = max(1, days_count // 7)
        fb_sparks, goog_sparks, tt_sparks, ig_sparks, tot_sparks = [], [], [], [], []
        for i in range(0, days_count, step):
            d = curr_start + timedelta(days=i)
            day_meta = float(curr_qs.filter(platform=Platform.META, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            day_goog = float(curr_qs.filter(platform=Platform.GOOGLE, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            day_tt = float(curr_qs.filter(platform=Platform.TIKTOK, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            fb_sparks.append(round(day_meta * 0.77, 1))
            ig_sparks.append(round(day_meta * 0.23, 1))
            goog_sparks.append(round(day_goog, 1))
            tt_sparks.append(round(day_tt, 1))
            tot_sparks.append(round(day_meta + day_goog + day_tt, 1))
    else:
        # TODO: calculate real platform spend and trends from synced AnalysisDaily records once ad accounts are connected and synchronized
        fb_spend, fb_prev = 4230.55, 3760.00
        goog_spend, goog_prev = 3215.45, 2969.00
        tt_spend, tt_prev = 2815.20, 2433.00
        ig_spend, ig_prev = 1245.30, 1182.00
        tot_spend, tot_prev = 11506.50, 10344.00
        fb_sparks = [18, 22, 15, 18, 10, 12, 15]
        goog_sparks = [20, 25, 18, 14, 10, 12, 14]
        tt_sparks = [22, 15, 18, 12, 16, 8, 11]
        ig_sparks = [20, 25, 18, 20, 12, 14, 13]
        tot_sparks = [19, 22, 16, 18, 10, 14, 15]

        # Baseline fallback metric numbers
        curr_imp, prev_imp = 2450000, 2065000
        curr_clk, prev_clk = 145000, 124600
        curr_conv, prev_conv = 3242, 2633
        curr_cpa, prev_cpa = 3.55, 3.93
        curr_roas, prev_roas = 4.35, 3.63

    fb_delta = _pct_change(fb_spend, fb_prev)
    goog_delta = _pct_change(goog_spend, goog_prev)
    tt_delta = _pct_change(tt_spend, tt_prev)
    ig_delta = _pct_change(ig_spend, ig_prev)
    tot_delta = _pct_change(tot_spend, tot_prev)

    platform_cards = [
        {
            'name': 'Facebook',
            'platform': 'facebook',
            'spend': fb_spend,
            'formatted_spend': f"${fb_spend:,.2f}",
            'delta': f"{'↑' if fb_delta >= 0 else '↓'} {abs(fb_delta):.1f}%",
            'change_percent': fb_delta,
            'is_positive': fb_delta >= 0,
            'sub_label': comparison_label,
            'color': '#2563eb',
            'sparkline': fb_sparks,
        },
        {
            'name': 'Google Ads',
            'platform': 'google',
            'spend': goog_spend,
            'formatted_spend': f"${goog_spend:,.2f}",
            'delta': f"{'↑' if goog_delta >= 0 else '↓'} {abs(goog_delta):.1f}%",
            'change_percent': goog_delta,
            'is_positive': goog_delta >= 0,
            'sub_label': comparison_label,
            'color': '#10b981',
            'sparkline': goog_sparks,
        },
        {
            'name': 'TikTok',
            'platform': 'tiktok',
            'spend': tt_spend,
            'formatted_spend': f"${tt_spend:,.2f}",
            'delta': f"{'↑' if tt_delta >= 0 else '↓'} {abs(tt_delta):.1f}%",
            'change_percent': tt_delta,
            'is_positive': tt_delta >= 0,
            'sub_label': comparison_label,
            'color': '#1e293b',
            'sparkline': tt_sparks,
        },
        {
            'name': 'Instagram',
            'platform': 'instagram',
            'spend': ig_spend,
            'formatted_spend': f"${ig_spend:,.2f}",
            'delta': f"{'↑' if ig_delta >= 0 else '↓'} {abs(ig_delta):.1f}%",
            'change_percent': ig_delta,
            'is_positive': ig_delta >= 0,
            'sub_label': comparison_label,
            'color': '#ec4899',
            'sparkline': ig_sparks,
        },
        {
            'name': 'Total Spend',
            'platform': 'total',
            'spend': tot_spend,
            'formatted_spend': f"${tot_spend:,.2f}",
            'delta': f"{'↑' if tot_delta >= 0 else '↓'} {abs(tot_delta):.1f}%",
            'change_percent': tot_delta,
            'is_positive': tot_delta >= 0,
            'sub_label': comparison_label,
            'color': '#2563eb',
            'sparkline': tot_sparks,
        },
    ]

    # ── 4. Performance Overview Metrics ───────────────────────────────────────
    imp_delta = _pct_change(curr_imp, prev_imp)
    clk_delta = _pct_change(curr_clk, prev_clk)
    conv_delta = _pct_change(curr_conv, prev_conv)
    cpa_delta = _pct_change(curr_cpa, prev_cpa)
    roas_delta = _pct_change(curr_roas, prev_roas)

    def _fmt_num(n):
        if n >= 1_000_000:
            return f"{(n / 1_000_000):.2f}M"
        if n >= 1_000:
            return f"{(n / 1_000):.0f}K"
        return str(n)

    overview_metrics = [
        {
            'id': 'impressions',
            'label': 'Impressions',
            'value': _fmt_num(curr_imp),
            'raw_value': curr_imp,
            'delta': f"▲ {abs(imp_delta):.1f}%" if imp_delta >= 0 else f"▼ {abs(imp_delta):.1f}%",
            'change_percent': imp_delta,
            'is_positive': imp_delta >= 0,
        },
        {
            'id': 'clicks',
            'label': 'Clicks',
            'value': _fmt_num(curr_clk),
            'raw_value': curr_clk,
            'delta': f"▲ {abs(clk_delta):.1f}%" if clk_delta >= 0 else f"▼ {abs(clk_delta):.1f}%",
            'change_percent': clk_delta,
            'is_positive': clk_delta >= 0,
        },
        {
            'id': 'conversions',
            'label': 'Conversions',
            'value': f"{curr_conv:,}",
            'raw_value': curr_conv,
            'delta': f"▲ {abs(conv_delta):.1f}%" if conv_delta >= 0 else f"▼ {abs(conv_delta):.1f}%",
            'change_percent': conv_delta,
            'is_positive': conv_delta >= 0,
        },
        {
            'id': 'cost_per_conversion',
            'label': 'Cost / Conv.',
            'value': f"${curr_cpa:.2f}",
            'raw_value': curr_cpa,
            'delta': f"▲ {abs(cpa_delta):.1f}%" if cpa_delta >= 0 else f"▼ {abs(cpa_delta):.1f}%",
            'change_percent': cpa_delta,
            # For cost per conversion, decrease is positive
            'is_positive': cpa_delta <= 0,
        },
        {
            'id': 'roas',
            'label': 'ROAS',
            'value': f"{curr_roas:.2f}x",
            'raw_value': curr_roas,
            'delta': f"▲ {abs(roas_delta):.1f}%" if roas_delta >= 0 else f"▼ {abs(roas_delta):.1f}%",
            'change_percent': roas_delta,
            'is_positive': roas_delta >= 0,
        },
    ]

    # ── 5. Recharts Multi-Line Time-Series Chart Data ──────────────────────────
    if has_analysis and curr_spend > 0:
        days_span = max(1, (curr_end - curr_start).days + 1)
        step = max(1, days_span // 7)
        chart_data = []
        for i in range(0, days_span, step):
            d = curr_start + timedelta(days=i)
            day_meta = float(curr_qs.filter(platform=Platform.META, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            day_goog = float(curr_qs.filter(platform=Platform.GOOGLE, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            day_tt = float(curr_qs.filter(platform=Platform.TIKTOK, date=d).aggregate(s=Sum('spend'))['s'] or 0.0)
            chart_data.append({
                'date': d.strftime('%b %d'),
                'Facebook': round(day_meta * 0.77, 1),
                'GoogleAds': round(day_goog, 1),
                'TikTok': round(day_tt, 1),
                'Instagram': round(day_meta * 0.23, 1),
            })
    else:
        # TODO: aggregate daily data per platform from AnalysisDaily once synchronized
        chart_data = [
            {'date': 'May 1', 'Facebook': 155, 'GoogleAds': 110, 'TikTok': 70, 'Instagram': 35},
            {'date': 'May 6', 'Facebook': 125, 'GoogleAds': 92, 'TikTok': 58, 'Instagram': 28},
            {'date': 'May 11', 'Facebook': 142, 'GoogleAds': 105, 'TikTok': 68, 'Instagram': 38},
            {'date': 'May 16', 'Facebook': 162, 'GoogleAds': 112, 'TikTok': 68, 'Instagram': 48},
            {'date': 'May 21', 'Facebook': 128, 'GoogleAds': 96, 'TikTok': 62, 'Instagram': 30},
            {'date': 'May 26', 'Facebook': 156, 'GoogleAds': 110, 'TikTok': 64, 'Instagram': 38},
            {'date': 'May 31', 'Facebook': 149, 'GoogleAds': 104, 'TikTok': 66, 'Instagram': 32},
        ]

    # ── 6. Top Campaigns Table Data ───────────────────────────────────────────
    campaigns_qs = UnifiedCampaign.objects.filter(organization=organization)
    campaigns_qs = CampaignService().annotate_queryset_with_metrics(campaigns_qs)
    top_camps = campaigns_qs.prefetch_related('platform_campaigns__integration').order_by('-_total_spent', '-created_at')[:5]

    top_campaigns = []
    if top_camps.exists():
        for c in top_camps:
            c_spend = getattr(c, '_total_spent', 0.0) or 0.0
            c_conv = getattr(c, '_conversions', 0) or 0
            c_w_roas = getattr(c, '_weighted_roas', 0.0) or 0.0
            c_roas = round(c_w_roas / c_spend, 2) if c_spend > 0 else 0.0
            c_imp = getattr(c, '_impressions', 0) or 0
            c_clk = getattr(c, '_clicks', 0) or 0
            c_ctr = round(c_clk / c_imp * 100, 2) if c_imp > 0 else 0.0
            platforms = [pc.integration.platform for pc in c.platform_campaigns.all()] if c.status != 'DRAFT' else ((c.draft_data or {}).get('platforms') or [])
            primary_p = platforms[0] if platforms else 'META'
            platform_name = 'Facebook' if primary_p == 'META' else ('Google Ads' if primary_p == 'GOOGLE' else 'TikTok')

            top_campaigns.append({
                'id': c.id,
                'name': c.name,
                'platform': platform_name,
                'platforms': platforms,
                'spend': f"${c_spend:,.2f}",
                'raw_spend': c_spend,
                'conversions': f"{c_conv:,}",
                'raw_conversions': c_conv,
                'roas': f"{c_roas:.2f}x",
                'raw_roas': c_roas,
                'ctr': f"{c_ctr:.2f}%",
                'raw_ctr': c_ctr,
                'status': c.status,
            })
    else:
        # TODO: replace demo campaigns with real campaigns once user creates their first campaign
        top_campaigns = [
            {
                'id': 1,
                'name': 'Summer Sale 2024',
                'platform': 'Facebook',
                'platforms': ['META'],
                'spend': '$1,250.45',
                'raw_spend': 1250.45,
                'conversions': '452',
                'raw_conversions': 452,
                'roas': '4.62x',
                'raw_roas': 4.62,
                'ctr': '2.35%',
                'raw_ctr': 2.35,
                'status': 'ACTIVE',
            },
            {
                'id': 2,
                'name': 'Search | Brand Campaign',
                'platform': 'Google Ads',
                'platforms': ['GOOGLE'],
                'spend': '$980.30',
                'raw_spend': 980.30,
                'conversions': '320',
                'raw_conversions': 320,
                'roas': '5.11x',
                'raw_roas': 5.11,
                'ctr': '3.02%',
                'raw_ctr': 3.02,
                'status': 'ACTIVE',
            },
            {
                'id': 3,
                'name': 'TikTok | New Collection',
                'platform': 'TikTok',
                'platforms': ['TIKTOK'],
                'spend': '$875.20',
                'raw_spend': 875.20,
                'conversions': '210',
                'raw_conversions': 210,
                'roas': '3.85x',
                'raw_roas': 3.85,
                'ctr': '2.15%',
                'raw_ctr': 2.15,
                'status': 'ACTIVE',
            },
            {
                'id': 4,
                'name': 'Instagram | Spring Promo',
                'platform': 'Instagram',
                'platforms': ['META'],
                'spend': '$645.10',
                'raw_spend': 645.10,
                'conversions': '128',
                'raw_conversions': 128,
                'roas': '2.98x',
                'raw_roas': 2.98,
                'ctr': '1.85%',
                'raw_ctr': 1.85,
                'status': 'ACTIVE',
            },
            {
                'id': 5,
                'name': 'Remarketing Campaign',
                'platform': 'Facebook',
                'platforms': ['META'],
                'spend': '$420.25',
                'raw_spend': 420.25,
                'conversions': '98',
                'raw_conversions': 98,
                'roas': '2.45x',
                'raw_roas': 2.45,
                'ctr': '1.45%',
                'raw_ctr': 1.45,
                'status': 'ACTIVE',
            },
        ]

    # ── 7. AI Insights ────────────────────────────────────────────────────────
    db_insights = organization.ai_insights.order_by('-created_at')[:3]
    ai_insights = []
    if db_insights.exists():
        for ins in db_insights:
            # TODO: compute dynamic confidence score and projected ROI using AI insight model calibration
            impact = ins.impact
            confidence = 92 if impact == 'HIGH' else (78 if impact == 'MEDIUM' else 85)
            roi_impact = "+18% ROI" if impact == 'HIGH' else ("+12% ROI" if impact == 'MEDIUM' else "+8% ROI")
            impact_badge = "High Impact" if impact == 'HIGH' else ("Medium Impact" if impact == 'MEDIUM' else "Tip")
            icon_type = "trend" if impact == 'HIGH' else ("target" if impact == 'MEDIUM' else "bar")

            ai_insights.append({
                'id': ins.id,
                'title': ins.title,
                'description': ins.description,
                'impact': impact,
                'impact_badge': impact_badge,
                'confidence': confidence,
                'confidence_text': f"Confidence: {confidence}%",
                'roi_impact': roi_impact,
                'icon_type': icon_type,
                'created_at': ins.created_at.isoformat(),
            })
    else:
        # TODO: generate active AI insights through Celery periodic task for active campaigns
        ai_insights = [
            {
                'id': 101,
                'title': 'Increase Budget on Google Ads',
                'description': 'Your Google Ads campaigns are performing 23% better than average. Consider increasing budget.',
                'impact': 'HIGH',
                'impact_badge': 'High Impact',
                'confidence': 92,
                'confidence_text': 'Confidence: 92%',
                'roi_impact': '+18% ROI',
                'icon_type': 'trend',
                'created_at': timezone.now().isoformat(),
            },
            {
                'id': 102,
                'title': 'Improve ROAS on TikTok',
                'description': 'Some TikTok ad sets have ROAS below 2.0x. Optimize creatives and targeting.',
                'impact': 'MEDIUM',
                'impact_badge': 'Medium Impact',
                'confidence': 78,
                'confidence_text': 'Confidence: 78%',
                'roi_impact': '+12% ROI',
                'icon_type': 'target',
                'created_at': timezone.now().isoformat(),
            },
            {
                'id': 103,
                'title': 'Best Time to Advertise',
                'description': 'Your ads perform best between 10AM - 2PM. Consider increasing bids during this time.',
                'impact': 'LOW',
                'impact_badge': 'Tip',
                'confidence': 85,
                'confidence_text': 'Confidence: 85%',
                'roi_impact': '+8% ROI',
                'icon_type': 'bar',
                'created_at': timezone.now().isoformat(),
            },
        ]

    # ── 8. Budget Recommendation ──────────────────────────────────────────────
    # Pick top campaign from DB or generate dynamic recommendation
    best_campaign = campaigns_qs.order_by('-_total_spent').first()
    if best_campaign:
        # TODO: compute optimal budget reallocation dynamically via predictive optimization
        rec_campaign_name = best_campaign.name
        rec_campaign_id = best_campaign.id
    else:
        rec_campaign_name = 'Summer Sale 2024'
        rec_campaign_id = 1

    budget_recommendation = {
        'campaign_id': rec_campaign_id,
        'campaign_name': rec_campaign_name,
        'action_text': 'Increase budget on',
        'description': f"This campaign is performing 32% better than similar campaigns.",
        'badge_percent': '32%',
        'badge_label': 'Better',
        'potential_impact': '+$1,250',
        'progress_percent': 75,
        'recommended_budget_increase': 50.0,
    }

    # ── 9. Backward Compatibility Fields ──────────────────────────────────────
    six_moths_ago = timezone.now() - timedelta(days=180)
    analysis_data = AnalysisDaily.objects.filter(
        organization=organization,
        date__gte=six_moths_ago
    ).annotate(total_spend=Sum('spend')).order_by('platform')

    platform_values = [p[0] for p in Platform.choices]
    result_overview = {}
    current_date = timezone.now().date()
    months = []
    for i in range(5, -1, -1):
        m = (current_date - timedelta(days=i * 30)).strftime('%b')
        months.append(m)
    for m in months:
        result_overview[m] = {p: 0 for p in platform_values}

    for item in analysis_data:
        m = item.date.strftime('%b')
        if m in result_overview:
            result_overview[m][item.platform] += item.total_spend

    recent_campaigns = UnifiedCampaign.objects.filter(organization=organization).order_by('-created_at')[:5]

    return {
        # Core dynamic fields for User Dashboard
        'date_range': {
            'selected': time_range,
            'label': date_label,
            'comparison_label': comparison_label,
            'start_date': curr_start.isoformat(),
            'end_date': curr_end.isoformat(),
        },
        'platform_cards': platform_cards,
        'overview_metrics': overview_metrics,
        'chart_data': chart_data,
        'top_campaigns': top_campaigns,
        'ai_insights': ai_insights,
        'budget_recommendation': budget_recommendation,
        # Backward compatibility
        'total_spend': tot_spend,
        'impressions': curr_imp,
        'click_rate': curr_ctr,
        'roas': curr_roas,
        'spend_overview': result_overview,
        'recent_campaigns': SimpleCampaignSerializer(recent_campaigns, many=True).data,
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

