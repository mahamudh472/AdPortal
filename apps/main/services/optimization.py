"""Rule-based optimization intelligence.

The LLM (``apps.main.ai_services``) only writes explanatory copy. Every number the
dashboard shows is computed here from the organization's own ``AnalysisDaily`` /
``AnalysisBreakdownDaily`` rows: relative performance versus the org median, the
confidence score, the projected effect range, the budget recommendation and the
applied-optimization savings.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.analysis.models import AnalysisBreakdownDaily, AnalysisDaily
from apps.main.models import AIInsight, AppliedOptimization, CampaignBudget, UnifiedCampaign

# Minimum sample sizes before we are willing to make a claim.
MIN_SPEND = 10.0
MIN_IMPRESSIONS = 1_000
MIN_CONVERSIONS = 3
DEFAULT_WINDOW_DAYS = 30

ACTION_BY_TYPE = {
    AIInsight.RecommendationType.BUDGET_SHIFT: ('Apply Suggestion', 'apply'),
    AIInsight.RecommendationType.BUDGET_INCREASE: ('Apply Suggestion', 'apply'),
    AIInsight.RecommendationType.REFRESH_CREATIVE: ('Fix with AI', 'fix'),
    AIInsight.RecommendationType.IMPROVE_TARGETING: ('Fix with AI', 'fix'),
    AIInsight.RecommendationType.SCHEDULE: ('Generate Suggestions', 'generate'),
    AIInsight.RecommendationType.GENERAL: ('Generate Suggestions', 'generate'),
}

IMPACT_RANK = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
ICON_BY_TYPE = {
    AIInsight.RecommendationType.BUDGET_SHIFT: 'trend',
    AIInsight.RecommendationType.BUDGET_INCREASE: 'trend',
    AIInsight.RecommendationType.REFRESH_CREATIVE: 'target',
    AIInsight.RecommendationType.IMPROVE_TARGETING: 'target',
    AIInsight.RecommendationType.SCHEDULE: 'bar',
    AIInsight.RecommendationType.GENERAL: 'bar',
}


def _median(values):
    values = [float(v) for v in values if v is not None]
    return statistics.median(values) if values else 0.0


def _ratio(numerator, denominator, scale=1.0):
    return (numerator / denominator * scale) if denominator else 0.0


def default_window(days=DEFAULT_WINDOW_DAYS):
    end = timezone.now().date()
    return end - timedelta(days=days - 1), end


def organization_currency(organization, days=DEFAULT_WINDOW_DAYS):
    """Primary reporting currency, without blending accounts that report in others."""
    start, end = default_window(days)
    rows = (
        AnalysisDaily.objects
        .filter(organization=organization, date__gte=start, date__lte=end)
        .values('currency').annotate(spend=Sum('spend'))
    )
    by_currency = {
        (row['currency'] or '').upper(): float(row['spend'] or 0) for row in rows
    }
    non_blank = {c: v for c, v in by_currency.items() if c}
    integration_currency = next(
        (
            integration.currency.upper()
            for integration in organization.integrations.filter(is_active=True)
            if integration.currency
        ),
        None,
    )
    if integration_currency and (integration_currency in non_blank or not non_blank):
        return integration_currency
    if non_blank:
        return max(non_blank, key=non_blank.get)
    return 'USD'


def campaign_metrics(organization, days=DEFAULT_WINDOW_DAYS, active_only=True, currency=None):
    """Per-campaign totals for the window, keyed by ``unified_campaign_id``."""
    start, end = default_window(days)
    rows = AnalysisDaily.objects.filter(
        organization=organization, date__gte=start, date__lte=end,
        unified_campaign__isnull=False,
    )
    if currency:
        rows = rows.filter(currency__in=['', currency.upper()])
    rows = (
        rows
        .values('unified_campaign_id')
        .annotate(
            spend=Sum('spend'),
            impressions=Sum('impressions'),
            clicks=Sum('clicks'),
            conversions=Sum('conversions'),
            conversion_value=Sum('conversion_value'),
            days=Count('date', distinct=True),
        )
    )
    metrics = {}
    for row in rows:
        spend = float(row['spend'] or 0)
        conversions = float(row['conversions'] or 0)
        value = float(row['conversion_value'] or 0)
        impressions = int(row['impressions'] or 0)
        clicks = int(row['clicks'] or 0)
        metrics[row['unified_campaign_id']] = {
            'campaign_id': row['unified_campaign_id'],
            'spend': spend,
            'impressions': impressions,
            'clicks': clicks,
            'conversions': conversions,
            'conversion_value': value,
            'days': row['days'] or 0,
            'roas': _ratio(value, spend),
            'cpa': _ratio(spend, conversions),
            'ctr': _ratio(clicks, impressions, 100),
            'cpc': _ratio(spend, clicks),
        }

    campaigns = UnifiedCampaign.objects.filter(organization=organization)
    if active_only:
        campaigns = campaigns.filter(status='ACTIVE')
    for campaign in campaigns.only('id', 'name', 'status', 'objective'):
        data = metrics.setdefault(campaign.id, {
            'campaign_id': campaign.id, 'spend': 0.0, 'impressions': 0,
            'clicks': 0, 'conversions': 0.0, 'conversion_value': 0.0,
            'days': 0, 'roas': 0.0, 'cpa': 0.0, 'ctr': 0.0, 'cpc': 0.0,
        })
        data['name'] = campaign.name
        data['status'] = campaign.status
        data['objective'] = campaign.objective
    return {cid: data for cid, data in metrics.items() if 'name' in data}


def campaign_metrics_for(campaign, days=DEFAULT_WINDOW_DAYS):
    """Totals for one campaign (used by the LLM insight task)."""
    start, end = default_window(days)
    aggregate = AnalysisDaily.objects.filter(
        unified_campaign=campaign, date__gte=start, date__lte=end
    ).aggregate(
        spend=Sum('spend'), impressions=Sum('impressions'), clicks=Sum('clicks'),
        conversions=Sum('conversions'), conversion_value=Sum('conversion_value'),
    )
    spend = float(aggregate['spend'] or 0)
    conversions = float(aggregate['conversions'] or 0)
    impressions = int(aggregate['impressions'] or 0)
    clicks = int(aggregate['clicks'] or 0)
    return {
        'spend': spend,
        'impressions': impressions,
        'clicks': clicks,
        'conversions': conversions,
        'conversion_value': float(aggregate['conversion_value'] or 0),
        'roas': _ratio(aggregate['conversion_value'] or 0, spend),
        'cpa': _ratio(spend, conversions),
        'ctr': _ratio(clicks, impressions, 100),
    }


def confidence_score(*, impressions=0, conversions=0, days=0, effect_ratio=0.0):
    """0-95 confidence from data volume, observed effect size and consistency."""
    volume = min(1.0, impressions / 100_000) * 35
    outcome = min(1.0, conversions / 100) * 35
    effect = min(1.0, abs(effect_ratio) / 0.5) * 20
    consistency = min(1.0, days / 14) * 10
    return max(20, min(95, round(volume + outcome + effect + consistency)))


def infer_recommendation_type(text):
    """Map LLM wording to a structured recommendation type."""
    text = (text or '').lower()
    if any(word in text for word in ('shift', 'reallocat', 'move budget', 'redistribut')):
        return AIInsight.RecommendationType.BUDGET_SHIFT
    if any(word in text for word in ('increase budget', 'scale', 'raise budget', 'spend more')):
        return AIInsight.RecommendationType.BUDGET_INCREASE
    if any(word in text for word in ('creative', 'fatigue', 'headline', 'copy', 'imagery', 'video')):
        return AIInsight.RecommendationType.REFRESH_CREATIVE
    if any(word in text for word in ('target', 'audience', 'keyword', 'placement', 'demographic')):
        return AIInsight.RecommendationType.IMPROVE_TARGETING
    if any(word in text for word in ('schedule', 'time of day', 'hour', 'daypart')):
        return AIInsight.RecommendationType.SCHEDULE
    return AIInsight.RecommendationType.GENERAL


def _percentage_range(low, high):
    low, high = int(round(low)), int(round(high))
    if low > high:
        low, high = high, low
    return [low, high]


def _campaign_platform(campaign):
    platforms = list(
        campaign.platform_campaigns.values_list('integration__platform', flat=True).distinct()
    )
    return campaigns_platform_label(platforms)


def campaigns_platform_label(platforms):
    if not platforms:
        return 'META'
    return platforms[0]


def _daily_budget(campaign, fallback):
    budget = (
        CampaignBudget.objects.filter(campaign=campaign)
        .order_by('platform').first()
    )
    if budget and budget.daily_budget_minor:
        return budget.daily_budget_minor / 100
    return fallback


def _best_hour_window(organization, end, days=30):
    """Best 3-hour window by conversion rate (CTR fallback) with a volume floor."""
    start = end - timedelta(days=days - 1)
    rows = (
        AnalysisBreakdownDaily.objects
        .filter(organization=organization, dimension='hour',
                date__gte=start, date__lte=end)
        .values('key')
        .annotate(impressions=Sum('impressions'), clicks=Sum('clicks'),
                  spend=Sum('spend'), conversions=Sum('conversions'))
    )
    hours = {}
    for row in rows:
        try:
            hour = int(row['key'])
        except (TypeError, ValueError):
            continue
        hours[hour] = {
            'impressions': int(row['impressions'] or 0),
            'clicks': int(row['clicks'] or 0),
            'spend': float(row['spend'] or 0),
            'conversions': float(row['conversions'] or 0),
        }
    if len(hours) < 6:
        return None

    total_impressions = sum(v['impressions'] for v in hours.values())
    total_conversions = sum(v['conversions'] for v in hours.values())
    total_clicks = sum(v['clicks'] for v in hours.values())
    if total_impressions < MIN_IMPRESSIONS:
        return None
    use_conversions = total_conversions > 0
    overall = (_ratio(total_conversions, total_impressions) if use_conversions
               else _ratio(total_clicks, total_impressions))
    if not overall:
        return None

    best = None
    for start_hour in range(24):
        window = [hours.get((start_hour + offset) % 24) for offset in range(3)]
        window = [w for w in window if w]
        if len(window) < 3:
            continue
        impressions = sum(w['impressions'] for w in window)
        conversions = sum(w['conversions'] for w in window)
        clicks = sum(w['clicks'] for w in window)
        if impressions < MIN_IMPRESSIONS:
            continue
        rate = (conversions / impressions) if use_conversions else _ratio(clicks, impressions)
        if rate <= overall:
            continue
        lift = rate / overall - 1
        candidate = {
            'start': start_hour,
            'end': (start_hour + 2) % 24,
            'impressions': impressions,
            'lift': lift,
        }
        if best is None or candidate['lift'] > best['lift']:
            best = candidate
    return best


def _persist_insight(*, organization, campaign, title, description, impact,
                     recommendation_type, params, expected_delta, confidence):
    existing = (
        AIInsight.objects
        .filter(organization=organization, campaign=campaign, title=title)
        .order_by('-created_at')
        .first()
    )
    defaults = {
        'description': description,
        'impact': impact,
        'recommendation_type': recommendation_type,
        'params': params,
        'expected_delta': expected_delta,
        'confidence': confidence,
        'status': AIInsight.InsightStatus.OPEN,
        'applied_at': None,
    }
    if existing:
        for key, value in defaults.items():
            setattr(existing, key, value)
        existing.save(update_fields=list(defaults))
        return existing, False
    return AIInsight.objects.create(
        organization=organization, campaign=campaign, title=title, **defaults
    ), True


def generate_rule_insights(organization):
    """Create/refresh the open insights for an organization. Returns ``(created, updated)``."""
    currency = organization_currency(organization)
    metrics = campaign_metrics(organization, currency=currency)
    candidates = [m for m in metrics.values() if m['spend'] >= MIN_SPEND]
    if not candidates:
        return 0, 0

    revenue_known = any(m['conversion_value'] > 0 for m in candidates)
    comparable = [m for m in candidates if (m['conversions'] >= MIN_CONVERSIONS or revenue_known)]
    if not comparable:
        comparable = candidates

    median_roas = _median([m['roas'] for m in comparable if m['roas'] > 0])
    median_cpa = _median([m['cpa'] for m in comparable if m['cpa'] > 0])
    median_ctr = _median([m['ctr'] for m in comparable if m['ctr'] > 0])

    campaigns = {c.id: c for c in UnifiedCampaign.objects.filter(
        organization=organization, id__in=[m['campaign_id'] for m in comparable]
    )}
    proposed = []

    best = max(comparable, key=lambda m: m['roas']) if revenue_known else None
    worst = max(comparable, key=lambda m: m['cpa']) if median_cpa else None

    if best and median_roas and best['roas'] > median_roas * 1.15:
        campaign = campaigns.get(best['campaign_id'])
        if campaign:
            ratio = best['roas'] / median_roas - 1
            effect = min(0.25, ratio / 2)
            daily_budget = _daily_budget(campaign, _ratio(best['spend'], max(1, best['days'])))
            increase_pct = max(10, min(30, round(effect * 100)))
            confidence = confidence_score(
                impressions=best['impressions'], conversions=best['conversions'],
                days=best['days'], effect_ratio=ratio,
            )
            description = (
                f"ROAS is {best['roas']:.2f}x versus a {median_roas:.2f}x median across "
                f"your campaigns ({ratio * 100:.0f}% better). Increasing the daily budget "
                f"by {increase_pct}% projects roughly "
                f"{best['conversions'] * effect:.1f} extra conversions over 30 days."
            )
            proposed.append(dict(
                campaign=campaign,
                title=f"Increase budget on {campaign.name}",
                description=description,
                impact='HIGH' if ratio >= 0.5 else 'MEDIUM',
                recommendation_type=AIInsight.RecommendationType.BUDGET_INCREASE,
                params={
                    'campaign_id': campaign.id,
                    'platform': _campaign_platform(campaign),
                    'budget_change_percent': increase_pct,
                    'daily_budget': round(daily_budget, 2),
                },
                expected_delta={
                    'roas': _percentage_range(5, max(8, effect * 100)),
                    'conversions': _percentage_range(3, max(5, effect * 100)),
                },
                confidence=confidence,
            ))

    if worst and median_cpa and worst['cpa'] > median_cpa * 1.25 and worst['campaign_id'] != getattr(best, 'campaign_id', None):
        campaign = campaigns.get(worst['campaign_id'])
        if campaign:
            ratio = worst['cpa'] / median_cpa - 1
            confidence = confidence_score(
                impressions=worst['impressions'], conversions=worst['conversions'],
                days=worst['days'], effect_ratio=ratio,
            )
            description = (
                f"CPA is {worst['cpa']:.2f} versus a {median_cpa:.2f} median across your "
                f"campaigns ({ratio * 100:.0f}% higher). Shifting budget away from this "
                f"campaign should lower blended cost per result."
            )
            proposed.append(dict(
                campaign=campaign,
                title=f"Shift budget away from {campaign.name}",
                description=description,
                impact='HIGH' if ratio >= 0.5 else 'MEDIUM',
                recommendation_type=AIInsight.RecommendationType.BUDGET_SHIFT,
                params={
                    'campaign_id': campaign.id,
                    'platform': _campaign_platform(campaign),
                    'budget_change_percent': -20,
                },
                expected_delta={
                    'cost_per_result': _percentage_range(-15, -8),
                    'roas': _percentage_range(5, 12),
                },
                confidence=confidence,
            ))

    if median_ctr:
        low_ctr = [m for m in comparable if m['impressions'] >= MIN_IMPRESSIONS and m['ctr'] < median_ctr * 0.7]
        for metric_row in sorted(low_ctr, key=lambda m: m['impressions'], reverse=True)[:1]:
            campaign = campaigns.get(metric_row['campaign_id'])
            if not campaign:
                continue
            ratio = (median_ctr - metric_row['ctr']) / median_ctr
            proposed.append(dict(
                campaign=campaign,
                title=f"Refresh creative for {campaign.name}",
                description=(
                    f"CTR is {metric_row['ctr']:.2f}% versus a {median_ctr:.2f}% median "
                    f"({ratio * 100:.0f}% below). Refreshing the headline and first visual "
                    f"should recover click-through."
                ),
                impact='MEDIUM' if ratio < 0.5 else 'HIGH',
                recommendation_type=AIInsight.RecommendationType.REFRESH_CREATIVE,
                params={'campaign_id': campaign.id, 'platform': _campaign_platform(campaign)},
                expected_delta={'ctr': _percentage_range(5, max(10, ratio * 25))},
                confidence=confidence_score(
                    impressions=metric_row['impressions'], conversions=metric_row['conversions'],
                    days=metric_row['days'], effect_ratio=ratio,
                ),
            ))

    window = _best_hour_window(organization, timezone.now().date())
    if window and best:
        campaign = campaigns.get(best['campaign_id'])
        if campaign:
            proposed.append(dict(
                campaign=campaign,
                title=f"Shift schedule to {window['start']:02d}:00-{window['end']:02d}:59",
                description=(
                    f"The {window['start']:02d}:00-{window['end']:02d}:59 window converts "
                    f"{window['lift'] * 100:.0f}% above your average hour. Weighting bids "
                    f"toward it should improve efficiency."
                ),
                impact='LOW',
                recommendation_type=AIInsight.RecommendationType.SCHEDULE,
                params={
                    'campaign_id': campaign.id,
                    'start_hour': window['start'],
                    'end_hour': window['end'],
                },
                expected_delta={
                    'conversions': _percentage_range(3, max(5, window['lift'] * 100)),
                    'cost_per_result': _percentage_range(-8, -3),
                },
                confidence=confidence_score(
                    impressions=window['impressions'], conversions=best['conversions'],
                    days=best['days'], effect_ratio=window['lift'],
                ),
            ))

    proposed.sort(
        key=lambda item: (IMPACT_RANK.get(item['impact'], 0), item['confidence']),
        reverse=True,
    )

    created = updated = 0
    for item in proposed[:4]:
        _, was_created = _persist_insight(organization=organization, **item)
        created += int(was_created)
        updated += int(not was_created)
    return created, updated


def build_budget_recommendation(organization):
    """The dashboard's budget card, or ``None`` when no campaign qualifies."""
    currency = organization_currency(organization)
    metrics = campaign_metrics(organization, currency=currency)
    candidates = [
        m for m in metrics.values()
        if m['spend'] >= MIN_SPEND and m['days'] >= 3 and m['conversions'] > 0
    ]
    if not candidates:
        return None

    revenue_known = any(m['conversion_value'] > 0 for m in candidates)
    if revenue_known:
        median = _median([m['roas'] for m in candidates if m['roas'] > 0])
        if not median:
            return None
        best = max(candidates, key=lambda m: m['roas'])
        if best['roas'] <= median * 1.05:
            return None
        better = (best['roas'] / median - 1) * 100
        metric_label = 'ROAS'
    else:
        median = _median([m['cpa'] for m in candidates if m['cpa'] > 0])
        if not median:
            return None
        best = min(candidates, key=lambda m: m['cpa'])
        if best['cpa'] >= median * 0.95:
            return None
        better = (median / best['cpa'] - 1) * 100
        metric_label = 'CPA'

    campaign = UnifiedCampaign.objects.filter(id=best['campaign_id']).first()
    if not campaign:
        return None

    average_daily_spend = _ratio(best['spend'], max(1, best['days']))
    current_budget = _daily_budget(campaign, average_daily_spend)
    increase_pct = max(0.10, min(0.30, 0.10 + better / 200))
    increase_amount = round(max(5.0, current_budget * increase_pct), 2)

    # Marginal CPA with a haircut: spend does not scale linearly.
    extra_conversions = 0.0
    if best['cpa']:
        extra_conversions = (increase_amount * 30 / best['cpa']) * 0.8
    extra_revenue = extra_conversions * _ratio(best['conversion_value'], best['conversions'])

    return {
        'campaign_id': campaign.id,
        'campaign_name': campaign.name,
        'action_text': 'Increase budget on',
        'description': (
            f"This campaign's {metric_label} is {better:.0f}% better than your "
            f"other campaigns."
        ),
        'badge_percent': f"{better:.0f}%",
        'badge_label': 'Better',
        'potential_impact': f"+{round(extra_conversions)} conversions / 30d",
        'potential_conversions': round(extra_conversions),
        'potential_revenue': round(extra_revenue, 2),
        'progress_percent': max(1, min(100, round(better))),
        'recommended_budget_increase': increase_amount,
        'current_daily_budget': round(current_budget, 2),
        'currency': campaign.currency or '',
        'can_apply': CampaignBudget.objects.filter(campaign=campaign).exists(),
    }


def get_optimization_summary(organization):
    insights = AIInsight.objects.filter(
        organization=organization, status=AIInsight.InsightStatus.OPEN
    )
    applied = AppliedOptimization.objects.filter(
        organization=organization,
        status=AppliedOptimization.Status.APPLIED,
        created_at__date=timezone.now().date(),
    )
    since = timezone.now() - timedelta(days=30)
    savings = 0.0
    for entry in AppliedOptimization.objects.filter(
        organization=organization,
        status=AppliedOptimization.Status.APPLIED,
        created_at__gte=since,
    ):
        savings += float((entry.measured_impact or {}).get('savings') or 0)
    return {
        'active_insights': insights.count(),
        'high_priority': insights.filter(impact='HIGH').count(),
        'applied_today': applied.count(),
        'est_savings': round(savings, 2),
    }


def get_potential_impact(organization):
    """Aggregate the projected deltas of the open insights."""
    totals = {'conversions': [0.0, 0.0], 'cost_per_result': [0.0, 0.0], 'roas': [0.0, 0.0]}
    for insight in AIInsight.objects.filter(
        organization=organization, status=AIInsight.InsightStatus.OPEN
    ):
        delta = insight.expected_delta or {}
        for metric, value in delta.items():
            if metric not in totals or not isinstance(value, (list, tuple)) or len(value) != 2:
                continue
            totals[metric][0] += float(value[0])
            totals[metric][1] += float(value[1])

    def format_range(low, high):
        if low == 0 and high == 0:
            return '—'
        if low == high:
            return f"{low:+.0f}%"
        return f"{low:+.0f}% to {high:+.0f}%"

    return {
        'conversions': format_range(*totals['conversions']),
        'cost_per_result': format_range(*totals['cost_per_result']),
        'roas': format_range(*totals['roas']),
    }


def get_optimization_history(organization, limit=20):
    entries = AppliedOptimization.objects.filter(organization=organization)[:limit]
    history = []
    for entry in entries:
        measured = entry.measured_impact or {}
        impact = measured.get('summary') or ''
        if not impact:
            impact = entry.error_message if entry.status == AppliedOptimization.Status.FAILED else 'Awaiting measurement'
        history.append({
            'id': str(entry.id),
            'title': entry.title,
            'time': entry.created_at.isoformat(),
            'impact': impact,
            'status': entry.get_status_display(),
        })
    return history


def extract_roi_impact(insight):
    delta = (insight.expected_delta or {}).get('roas')
    if not isinstance(delta, (list, tuple)) or len(delta) != 2:
        return '—'
    return f"{delta[0]:+.0f}% to {delta[1]:+.0f}% ROAS"


def measure_applied_optimizations(now=None, window_days=7):
    """Fill ``measured_impact`` for applied changes once a full post-change week exists."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=window_days)
    entries = AppliedOptimization.objects.filter(
        status=AppliedOptimization.Status.APPLIED,
        created_at__lte=cutoff,
        measured_impact={},
    )
    measured = 0
    for entry in entries.iterator():
        applied_day = timezone.localtime(entry.created_at).date()
        pre_start = applied_day - timedelta(days=window_days)
        pre_end = applied_day - timedelta(days=1)
        post_start = applied_day
        post_end = min(applied_day + timedelta(days=window_days - 1), now.date())
        if post_end < post_start:
            continue

        def totals(start, end):
            return AnalysisDaily.objects.filter(
                unified_campaign=entry.campaign, date__gte=start, date__lte=end
            ).aggregate(
                spend=Sum('spend'), conversions=Sum('conversions'),
                conversion_value=Sum('conversion_value'),
            )

        pre, post = totals(pre_start, pre_end), totals(post_start, post_end)
        if not post['spend']:
            continue
        pre_spend, post_spend = float(pre['spend'] or 0), float(post['spend'] or 0)
        pre_conv, post_conv = float(pre['conversions'] or 0), float(post['conversions'] or 0)
        pre_value, post_value = float(pre['conversion_value'] or 0), float(post['conversion_value'] or 0)
        pre_cpa = _ratio(pre_spend, pre_conv)
        post_cpa = _ratio(post_spend, post_conv)
        pre_roas = _ratio(pre_value, pre_spend)
        post_roas = _ratio(post_value, post_spend)
        savings = max(0.0, (pre_cpa - post_cpa) * post_conv) if pre_cpa and post_conv else 0.0
        parts = []
        if pre_cpa and post_cpa:
            parts.append(f"CPA {_ratio(post_cpa - pre_cpa, pre_cpa, 100):+.0f}%")
        if pre_roas and post_roas:
            parts.append(f"ROAS {_ratio(post_roas - pre_roas, pre_roas, 100):+.0f}%")
        entry.measured_impact = {
            'summary': f"{' / '.join(parts)} over {window_days} days" if parts else 'Measured',
            'savings': round(savings, 2),
            'pre': {
                'spend': round(pre_spend, 2), 'conversions': pre_conv,
                'cpa': round(pre_cpa, 2), 'roas': round(pre_roas, 2),
            },
            'post': {
                'spend': round(post_spend, 2), 'conversions': post_conv,
                'cpa': round(post_cpa, 2), 'roas': round(post_roas, 2),
            },
            'measured_at': now.isoformat(),
        }
        entry.save(update_fields=['measured_impact'])
        measured += 1
    return measured
