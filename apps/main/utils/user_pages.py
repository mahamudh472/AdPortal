"""
Data helpers for the user-dashboard pages (campaign list, campaign details,
analytics, reports, AI optimization). Everything here is computed from
``AnalysisDaily`` unless a ``TODO`` says otherwise.
"""
from collections import defaultdict
from datetime import timedelta

from django.db.models import Sum, F, FloatField, ExpressionWrapper
from django.utils import timezone

from apps.analysis.models import AnalysisDaily

PLATFORM_LABELS = {
    'META': 'Meta',
    'GOOGLE': 'Google',
    'TIKTOK': 'TikTok',
}


def format_trend(current, previous):
    """Return an arrow string such as '↑ 12.5%' / '↓ 2.1%' comparing two values.

    Returns ``None`` when there is nothing to compare (both periods empty) so
    the frontend can render a neutral placeholder instead of a made-up number.
    """
    current = current or 0
    previous = previous or 0
    if current == 0 and previous == 0:
        return None
    if previous == 0:
        return '↑ 100%'
    change = (current - previous) / previous * 100
    if abs(change) < 0.05:
        return '→ 0%'
    arrow = '↑' if change > 0 else '↓'
    return f'{arrow} {abs(change):.1f}%'


def _ratio(numerator, denominator, scale=1.0):
    return (numerator / denominator * scale) if denominator else 0.0


def get_campaign_list_extras(campaign_ids, days=7):
    """Trend strings + daily-clicks sparkline for each campaign in ``campaign_ids``.

    Compares the last ``days`` days with the ``days`` days before them.
    Returns ``{campaign_id: {ctr_trend, conversions_trend, roas_trend, sparkline_data}}``.
    """
    campaign_ids = list(campaign_ids)
    if not campaign_ids:
        return {}

    today = timezone.now().date()
    curr_start = today - timedelta(days=days - 1)
    prev_start = curr_start - timedelta(days=days)

    rows = (
        AnalysisDaily.objects
        .filter(unified_campaign_id__in=campaign_ids, date__gte=prev_start, date__lte=today)
        .values('unified_campaign_id', 'date')
        .annotate(
            impressions_sum=Sum('impressions'),
            clicks_sum=Sum('clicks'),
            conversions_sum=Sum('conversions'),
            spend_sum=Sum('spend'),
            weighted_roas_sum=Sum(ExpressionWrapper(F('roas') * F('spend'), output_field=FloatField())),
        )
    )

    def empty_bucket():
        return {'impressions': 0, 'clicks': 0, 'conversions': 0, 'spend': 0.0, 'weighted_roas': 0.0}

    curr = defaultdict(empty_bucket)
    prev = defaultdict(empty_bucket)
    daily_clicks = defaultdict(lambda: defaultdict(int))

    for row in rows:
        cid = row['unified_campaign_id']
        bucket = curr[cid] if row['date'] >= curr_start else prev[cid]
        bucket['impressions'] += row['impressions_sum'] or 0
        bucket['clicks'] += row['clicks_sum'] or 0
        bucket['conversions'] += row['conversions_sum'] or 0
        bucket['spend'] += row['spend_sum'] or 0.0
        bucket['weighted_roas'] += row['weighted_roas_sum'] or 0.0
        if row['date'] >= curr_start:
            daily_clicks[cid][row['date']] += row['clicks_sum'] or 0

    date_axis = [curr_start + timedelta(days=i) for i in range(days)]
    extras = {}
    for cid in campaign_ids:
        c, p = curr[cid], prev[cid]
        extras[cid] = {
            'ctr_trend': format_trend(
                _ratio(c['clicks'], c['impressions'], 100), _ratio(p['clicks'], p['impressions'], 100)
            ),
            'conversions_trend': format_trend(c['conversions'], p['conversions']),
            'roas_trend': format_trend(
                _ratio(c['weighted_roas'], c['spend']), _ratio(p['weighted_roas'], p['spend'])
            ),
            'sparkline_data': [daily_clicks[cid].get(d, 0) for d in date_axis],
        }
    return extras


def get_campaign_placements(campaign):
    """Spend share per platform for one campaign (used by the details page).

    Falls back to impressions share when no spend has been recorded yet, and to
    an equal split of the connected platforms when there is no data at all.
    """
    rows = list(
        AnalysisDaily.objects
        .filter(unified_campaign=campaign)
        .values('platform')
        .annotate(spend_sum=Sum('spend'), impressions_sum=Sum('impressions'), clicks_sum=Sum('clicks'))
    )
    total_spend = sum(r['spend_sum'] or 0 for r in rows)
    total_impressions = sum(r['impressions_sum'] or 0 for r in rows)

    placements = []
    for r in rows:
        if total_spend > 0:
            percent = (r['spend_sum'] or 0) / total_spend * 100
        elif total_impressions > 0:
            percent = (r['impressions_sum'] or 0) / total_impressions * 100
        else:
            percent = 0
        placements.append({
            'platform': r['platform'],
            'label': PLATFORM_LABELS.get(r['platform'], r['platform']),
            'spend': round(r['spend_sum'] or 0, 2),
            'impressions': r['impressions_sum'] or 0,
            'clicks': r['clicks_sum'] or 0,
            'percent': round(percent, 1),
        })
    placements.sort(key=lambda p: p['percent'], reverse=True)
    return placements


def build_platform_insights(analysis_qs):
    """Per-platform highlight cards for the Analytics page.

    Each entry is ``{'platform', 'label', 'value'}`` or ``None`` if no platform
    qualifies (e.g. no conversions recorded yet).
    """
    rows = (
        analysis_qs
        .values('platform')
        .annotate(
            spend_sum=Sum('spend'),
            impressions_sum=Sum('impressions'),
            clicks_sum=Sum('clicks'),
            conversions_sum=Sum('conversions'),
            weighted_roas_sum=Sum(ExpressionWrapper(F('roas') * F('spend'), output_field=FloatField())),
        )
    )
    stats = []
    for r in rows:
        spend = r['spend_sum'] or 0
        stats.append({
            'platform': r['platform'],
            'spend': spend,
            'conversions': r['conversions_sum'] or 0,
            'ctr': _ratio(r['clicks_sum'] or 0, r['impressions_sum'] or 0, 100),
            'roas': _ratio(r['weighted_roas_sum'] or 0, spend),
            'cpa': _ratio(spend, r['conversions_sum'] or 0),
        })

    def pick(candidates, key, reverse, fmt):
        candidates = [s for s in candidates if key(s) > 0]
        if not candidates:
            return None
        best = sorted(candidates, key=key, reverse=reverse)[0]
        return {
            'platform': best['platform'],
            'label': PLATFORM_LABELS.get(best['platform'], best['platform']),
            'value': fmt(best),
        }

    return {
        'top_performing_platform': pick(stats, lambda s: s['roas'], True, lambda s: f"{s['roas']:.2f}x ROAS"),
        'most_conversions_platform': pick(stats, lambda s: s['conversions'], True, lambda s: f"{s['conversions']:,} conversions"),
        'best_click_rate_platform': pick(stats, lambda s: s['ctr'], True, lambda s: f"{s['ctr']:.2f}% CTR"),
        'lowest_cost_per_conversion': pick(stats, lambda s: s['cpa'], False, lambda s: f"${s['cpa']:.2f} / conversion"),
    }


def build_report_insights(organization, start_date=None, end_date=None):
    """Aggregate highlights shown in the Reports page sidebar."""
    today = timezone.now().date()
    end_date = end_date or today
    start_date = start_date or (end_date - timedelta(days=29))

    qs = AnalysisDaily.objects.filter(organization=organization, date__gte=start_date, date__lte=end_date)
    totals = qs.aggregate(
        spend_sum=Sum('spend'),
        impressions_sum=Sum('impressions'),
        clicks_sum=Sum('clicks'),
        conversions_sum=Sum('conversions'),
    )
    impressions = totals['impressions_sum'] or 0
    clicks = totals['clicks_sum'] or 0
    conversions = totals['conversions_sum'] or 0

    best = (
        qs.values('unified_campaign__name')
        .annotate(
            spend_sum=Sum('spend'),
            weighted_roas_sum=Sum(ExpressionWrapper(F('roas') * F('spend'), output_field=FloatField())),
        )
        .filter(spend_sum__gt=0)
    )
    top_campaign = None
    for row in best:
        roas = _ratio(row['weighted_roas_sum'] or 0, row['spend_sum'] or 0)
        if top_campaign is None or roas > top_campaign['roas']:
            top_campaign = {'name': row['unified_campaign__name'], 'roas': round(roas, 2)}

    return {
        'period': {'start_date': start_date.isoformat(), 'end_date': end_date.isoformat()},
        'top_campaign': top_campaign,
        'total_spend': round(totals['spend_sum'] or 0, 2),
        'conversion_rate': round(_ratio(conversions, clicks, 100), 2),
        'total_impressions': impressions,
    }
