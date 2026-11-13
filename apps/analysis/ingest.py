"""
Shared helpers for the platform analytics adapters (Meta / Google / TikTok).

The adapters fetch and parse platform responses; everything that writes to
``AnalysisDaily`` / ``AnalysisBreakdownDaily`` or interprets "what counts as a
conversion" lives here so the three platforms behave the same.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.analysis.models import AnalysisBreakdownDaily, AnalysisDaily

logger = logging.getLogger(__name__)

# Platforms revise conversions for weeks (attribution windows, conversion lag), so every
# scheduled run re-pulls this many days.
ROLLING_WINDOW_DAYS = 28
# Meta keeps hourly data for 13 months; use the same horizon for the first-sync backfill.
BACKFILL_MAX_DAYS = 395

BREAKDOWN_DIMENSIONS = AnalysisBreakdownDaily.Dimension.values


def default_window(start_date=None, end_date=None):
    """(start, end) with the rolling re-sync window as the default."""
    end = end_date or timezone.now().date()
    start = start_date or (end - timedelta(days=ROLLING_WINDOW_DAYS - 1))
    if start > end:
        start = end
    return start, end


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- Meta results
# "Conversions" = the result that matches the campaign objective. Meta reports the same
# event under several names (purchase / omni_purchase / pixel purchase); we take the
# first available name in priority order instead of summing, which would double count.
META_RESULT_ACTIONS = {
    'CONVERSIONS': ['omni_purchase', 'purchase', 'offsite_conversion.fb_pixel_purchase'],
    'LEAD_GENERATION': ['onsite_conversion.lead_grouped', 'lead', 'offsite_conversion.fb_pixel_lead'],
    'APP_PROMOTION': ['mobile_app_install', 'app_install'],
    'TRAFFIC': ['landing_page_view', 'link_click'],
    'ENGAGEMENT': ['post_engagement', 'page_engagement'],
    'AWARENESS': [],
}
# Used when the campaign has no recognised objective: any purchase-like result.
META_DEFAULT_ACTIONS = META_RESULT_ACTIONS['CONVERSIONS']


def _first_action_value(items, action_types):
    """Value of the first ``action_types`` entry present in a Meta ``actions`` list."""
    by_type = {i.get('action_type'): i.get('value') for i in (items or []) if isinstance(i, dict)}
    for action_type in action_types:
        if action_type in by_type:
            return action_type, safe_float(by_type[action_type])
    return None, 0.0


def extract_meta_result(row, objective=None):
    """(conversions, conversion_value) for one Meta insights row, based on the objective."""
    action_types = META_RESULT_ACTIONS.get((objective or '').upper(), META_DEFAULT_ACTIONS)
    if not action_types:
        return 0, 0.0
    chosen, conversions = _first_action_value(row.get('actions'), action_types)
    if chosen is None:
        return 0, 0.0
    # Value is only meaningful for the sales objective (action_values carries revenue).
    _, value = _first_action_value(row.get('action_values'), [chosen])
    return int(conversions), value


def parse_hour(value):
    """'14:00:00 - 14:59:59' (Meta) / '2024-01-01 14:00:00' (TikTok) / 14 (Google) -> '14'."""
    text = str(value).strip()
    if not text:
        return None
    if ' ' in text and ':' in text.split(' ')[-1] and '-' in text.split(' ')[0] and len(text.split(' ')[0]) == 10:
        text = text.split(' ')[1]  # date + time
    head = text.split(':')[0]
    try:
        hour = int(head)
    except ValueError:
        return None
    return str(hour) if 0 <= hour <= 23 else None


# ----------------------------------------------------------------- persistence
def save_daily(*, integration, unified_campaign, campaign_id, row_date, impressions=0, clicks=0,
               spend=0.0, conversions=0, conversion_value=0.0, reach=None, frequency=None,
               video_views=None, budget_type=None, budget_amount=None, device_breakdown=None):
    """Upsert one campaign/day row; derived ratios are computed here, not trusted from the API."""
    impressions, clicks, conversions = int(impressions or 0), int(clicks or 0), int(conversions or 0)
    spend, conversion_value = float(spend or 0), float(conversion_value or 0)
    defaults = {
        'organization': integration.organization,
        'unified_campaign': unified_campaign,
        'campaign_name': unified_campaign.name,
        'impressions': impressions,
        'clicks': clicks,
        'spend': spend,
        'ctr': (clicks / impressions * 100) if impressions else 0.0,
        'cpc': (spend / clicks) if clicks else 0.0,
        'cpm': (spend / impressions * 1000) if impressions else 0.0,
        'conversions': conversions,
        'cpa': (spend / conversions) if conversions else 0.0,
        'roas': (conversion_value / spend) if spend > 0 else 0.0,
        'conversion_value': conversion_value,
        'reach': reach,
        'frequency': frequency,
        'video_views': video_views,
        'currency': (integration.currency or '')[:3],
        'device_breakdown': device_breakdown or {},
        'budget_type': budget_type,
        'budget_amount': budget_amount,
        'synced_at': timezone.now(),
    }
    return AnalysisDaily.objects.update_or_create(
        platform=integration.platform,
        account_id=integration.ad_account_id,
        campaign_id=str(campaign_id),
        adgroup_id=None,
        date=row_date,
        defaults=defaults,
    )


def replace_breakdown(*, integration, unified_campaign, campaign_id, dimension, start, end, rows):
    """Replace one campaign's rows for ``dimension`` in [start, end].

    ``rows`` is an iterable of dicts: date, key, impressions, clicks, spend, conversions,
    conversion_value. Rows sharing (date, key) are summed. Delete-then-insert keeps the
    table exact when a key disappears from the platform's response.
    """
    if dimension not in BREAKDOWN_DIMENSIONS:
        raise ValueError(f'Unknown breakdown dimension: {dimension}')
    merged = defaultdict(lambda: {'impressions': 0, 'clicks': 0, 'spend': 0.0, 'conversions': 0.0, 'conversion_value': 0.0})
    for r in rows:
        key = str(r.get('key') or '').strip()[:100]
        if not key or not r.get('date'):
            continue
        bucket = merged[(r['date'], key)]
        bucket['impressions'] += int(r.get('impressions') or 0)
        bucket['clicks'] += int(r.get('clicks') or 0)
        bucket['spend'] += float(r.get('spend') or 0)
        bucket['conversions'] += float(r.get('conversions') or 0)
        bucket['conversion_value'] += float(r.get('conversion_value') or 0)

    scope = dict(
        platform=integration.platform,
        account_id=integration.ad_account_id,
        campaign_id=str(campaign_id),
        dimension=dimension,
    )
    objs = [
        AnalysisBreakdownDaily(
            organization=integration.organization,
            unified_campaign=unified_campaign,
            date=d, key=k,
            currency=(integration.currency or '')[:3],
            **scope, **vals,
        )
        for (d, k), vals in merged.items()
    ]
    with transaction.atomic():
        AnalysisBreakdownDaily.objects.filter(date__gte=start, date__lte=end, **scope).delete()
        AnalysisBreakdownDaily.objects.bulk_create(objs, batch_size=500)
    return len(objs)


def mark_sync_result(integration, failures=None):
    """Record when analytics last synced and which optional breakdowns failed."""
    integration.analytics_synced_at = timezone.now()
    integration.analytics_error = '; '.join(failures)[:2000] if failures else ''
    integration.save(update_fields=['analytics_synced_at', 'analytics_error'])
