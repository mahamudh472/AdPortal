"""
Guidance data for the campaign create/update wizard (the "AI" side panels).

Everything here is deterministic and derived from the organization, its connected
integrations and the draft campaign — no external calls — so the panels respond
instantly and are cheap. The numbers are planning estimates, not platform quotes.
"""
from decimal import Decimal, ROUND_HALF_UP

from apps.main.models import (
    AdIntegration,
    Organization,
    Platform,
    UnifiedCampaign,
    UnifiedObjective,
)

HEADLINE_MAX = 40
DESCRIPTION_MAX = 30
PRIMARY_TEXT_MAX = 125

CALL_TO_ACTIONS = [
    'Shop now', 'Learn More', 'Sign Up', 'Contact Us', 'Book Now', 'Download', 'Get Quote',
]

PLATFORM_CATALOG = {
    Platform.META: {
        'name': 'Meta (Facebook)',
        'description': 'Reach billions of people across Facebook, Instagram and Messenger.',
        'formats': ['Feed Ads', 'Stories', 'Reels', 'Messenger'],
        'reach_potential': 3_200_000_000,
        'best_for': ['Awareness', 'Retargeting'],
        'strong_objectives': [UnifiedObjective.AWARENESS, UnifiedObjective.ENGAGEMENT, UnifiedObjective.LEAD_GENERATION],
        'strength': 'Best for reach',
        'impact': {'cost': 'Medium', 'speed': 'Fast', 'performance': 'High'},
    },
    Platform.GOOGLE: {
        'name': 'Google Ads',
        'description': 'Show ads on Google Search, YouTube, and across the web.',
        'formats': ['Search', 'YouTube', 'Display', 'Gmail'],
        'reach_potential': 2_600_000_000,
        'best_for': ['Conversions', 'Sales'],
        'strong_objectives': [UnifiedObjective.CONVERSIONS, UnifiedObjective.TRAFFIC],
        'strength': 'Best for conversions',
        'impact': {'cost': 'Medium', 'speed': 'Fast', 'performance': 'High'},
    },
    Platform.TIKTOK: {
        'name': 'TikTok Ads',
        'description': 'Engage with Gen Z and millennials on TikTok.',
        'formats': ['In-Feed Ads', 'TopView', 'Spark Ads', 'Branded Effects'],
        'reach_potential': 1_500_000_000,
        'best_for': ['Engagement', 'Video Views'],
        'strong_objectives': [UnifiedObjective.ENGAGEMENT, UnifiedObjective.APP_PROMOTION, UnifiedObjective.AWARENESS],
        'strength': 'Best for engagement',
        'impact': {'cost': 'Low', 'speed': 'Fast', 'performance': 'High'},
    },
}

OBJECTIVE_CATALOG = {
    UnifiedObjective.CONVERSIONS: {
        'title': 'Conversions',
        'description': 'Drive sales, sign-ups, or other valuable actions on your website or app.',
        'best_for': ['Sales', 'Sign-ups', 'Purchases'],
    },
    UnifiedObjective.TRAFFIC: {
        'title': 'Traffic',
        'description': 'Send more people to your website or app.',
        'best_for': ['Website Visits', 'Landing Page Views', 'Clicks'],
    },
    UnifiedObjective.AWARENESS: {
        'title': 'Awareness',
        'description': 'Reach people most likely to remember your ads.',
        'best_for': ['Brand Awareness', 'Reach', 'Impressions'],
    },
    UnifiedObjective.ENGAGEMENT: {
        'title': 'Engagement',
        'description': 'Get more likes, comments, shares, and interactions.',
        'best_for': ['Post Engagement', 'Page Likes', 'Video Views'],
    },
    UnifiedObjective.LEAD_GENERATION: {
        'title': 'Lead Generation',
        'description': 'Collect leads and grow your customer base.',
        'best_for': ['Lead Forms', 'Info Requests', 'Consultations'],
    },
    UnifiedObjective.APP_PROMOTION: {
        'title': 'App Promotion',
        'description': 'Get more app installs and drive in-app actions.',
        'best_for': ['App Installs', 'In-App Actions', 'Engagement'],
    },
}

# Industry -> the objective that usually pays off best.
INDUSTRY_OBJECTIVE = {
    'ecommerce': UnifiedObjective.CONVERSIONS,
    'saas': UnifiedObjective.LEAD_GENERATION,
    'education': UnifiedObjective.LEAD_GENERATION,
    'finance': UnifiedObjective.LEAD_GENERATION,
    'agency': UnifiedObjective.AWARENESS,
}

# Typical cost-per-result (USD) by objective; used for the budget "estimated results".
COST_PER_RESULT = {
    UnifiedObjective.CONVERSIONS: Decimal('0.83'),
    UnifiedObjective.TRAFFIC: Decimal('0.35'),
    UnifiedObjective.AWARENESS: Decimal('0.08'),
    UnifiedObjective.ENGAGEMENT: Decimal('0.12'),
    UnifiedObjective.LEAD_GENERATION: Decimal('2.40'),
    UnifiedObjective.APP_PROMOTION: Decimal('1.60'),
}

# Share of the daily budget each platform should get, by objective.
PLATFORM_WEIGHTS = {
    UnifiedObjective.CONVERSIONS: {Platform.GOOGLE: 45, Platform.META: 35, Platform.TIKTOK: 20},
    UnifiedObjective.TRAFFIC: {Platform.GOOGLE: 40, Platform.META: 35, Platform.TIKTOK: 25},
    UnifiedObjective.AWARENESS: {Platform.META: 45, Platform.TIKTOK: 35, Platform.GOOGLE: 20},
    UnifiedObjective.ENGAGEMENT: {Platform.TIKTOK: 45, Platform.META: 40, Platform.GOOGLE: 15},
    UnifiedObjective.LEAD_GENERATION: {Platform.META: 45, Platform.GOOGLE: 40, Platform.TIKTOK: 15},
    UnifiedObjective.APP_PROMOTION: {Platform.TIKTOK: 40, Platform.META: 35, Platform.GOOGLE: 25},
}

BUDGET_PRESETS = [
    {'key': 'conservative', 'label': 'Conservative', 'daily_budget': 50},
    {'key': 'recommended', 'label': 'Recommended', 'daily_budget': 100},
    {'key': 'aggressive', 'label': 'Aggressive', 'daily_budget': 250},
]

REACH_THRESHOLDS = {'too_specific_below': 100_000, 'optimal_min': 630_000, 'optimal_max': 960_000, 'too_broad_above': 2_000_000}


def format_count(value):
    value = int(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


def _currency(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class CampaignWizardService:
    # ------------------------------------------------------------------ config
    def recommended_objective(self, organization):
        return INDUSTRY_OBJECTIVE.get(organization.industry or '', UnifiedObjective.CONVERSIONS)

    def get_config(self, organization, campaign=None):
        connected = set(
            AdIntegration.objects.filter(organization=organization, is_active=True)
            .values_list('platform', flat=True)
        )
        objective = (campaign.objective if campaign and campaign.objective else None) or self.recommended_objective(organization)

        platforms = []
        for key, meta in PLATFORM_CATALOG.items():
            platforms.append({
                'key': key.value,
                'name': meta['name'],
                'description': meta['description'],
                'formats': meta['formats'],
                'reach_potential': meta['reach_potential'],
                'reach_label': f"{format_count(meta['reach_potential'])}+ users",
                'best_for': meta['best_for'],
                'strength': meta['strength'],
                'impact': meta['impact'],
                'connected': key.value in connected,
                'recommended': objective in meta['strong_objectives'] and key.value in connected,
            })

        recommended_objective = self.recommended_objective(organization)
        objectives = [
            {
                'key': key.value,
                'title': meta['title'],
                'description': meta['description'],
                'best_for': meta['best_for'],
                'recommended': key == recommended_objective,
            }
            for key, meta in OBJECTIVE_CATALOG.items()
        ]

        return {
            'platforms': platforms,
            'platform_recommendation': self._platform_recommendation(platforms),
            'objectives': objectives,
            'objective_recommendation': {
                'objective': recommended_objective.value,
                'title': OBJECTIVE_CATALOG[recommended_objective]['title'],
                'summary': 'Highest ROI potential for your objective.',
                'reasons': ['Drives measurable results', 'Optimized for sales & sign-ups', 'Better return on ad spend'],
            },
            'call_to_actions': CALL_TO_ACTIONS,
            'limits': {
                'headline': HEADLINE_MAX,
                'description': DESCRIPTION_MAX,
                'primary_text': PRIMARY_TEXT_MAX,
            },
            'budget_presets': BUDGET_PRESETS,
        }

    @staticmethod
    def _platform_recommendation(platforms):
        picks = [p for p in platforms if p['recommended']] or [p for p in platforms if p['connected']]
        # Always surface the three platforms we can plan for so the panel is never empty.
        picks = picks or platforms
        return {
            'platforms': [{'key': p['key'], 'name': p['name'], 'strength': p['strength']} for p in picks],
            'expected_improvement_percent': 32 if len(picks) > 1 else 15,
        }

    # ----------------------------------------------------------- name suggestions
    def name_suggestions(self, organization, campaign=None, offset=0, count=3):
        draft = (campaign.draft_data if campaign else None) or {}
        brand = (organization.name or '').strip() or 'Brand'
        objective = (campaign.objective if campaign else '') or ''

        generic_goals = ['Conversions', 'Brand Awareness', 'Retargeting', 'Lead Gen', 'Traffic', 'App Installs']
        own_goal = OBJECTIVE_CATALOG[objective]['title'] if objective in OBJECTIVE_CATALOG else None
        goals = ([own_goal] if own_goal else []) + [g for g in generic_goals if g != own_goal]

        audiences = []
        locations = draft.get('locations') or []
        audiences += [loc for loc in locations if loc]
        keywords = [k.strip().title() for k in (draft.get('keywords') or '').split(',') if k.strip()]
        audiences += keywords[:3]
        audiences += ['Gen Z', 'Website Visitors', 'US', 'Lookalike']
        platform_names = {'META': 'Meta', 'GOOGLE': 'Google', 'TIKTOK': 'TikTok'}
        platforms = [platform_names.get(p, p) for p in (draft.get('platforms') or [])]
        audiences += platforms

        taken = set(
            UnifiedCampaign.objects.filter(organization=organization).values_list('name', flat=True)
        )
        if campaign:
            taken.discard(campaign.name)

        candidates, seen = [], set()
        for i, goal in enumerate(goals):
            for j in range(len(audiences)):
                audience = audiences[(i + j) % len(audiences)]
                name = f"{brand} – {goal} – {audience}"
                if name not in seen and name not in taken:
                    seen.add(name)
                    candidates.append(name)
        offset = max(0, offset) % max(1, len(candidates))
        window = (candidates + candidates)[offset:offset + count]
        return {'suggestions': window, 'next_offset': (offset + count) % max(1, len(candidates))}

    # -------------------------------------------------------------- budget
    def budget_recommendation(self, organization, platforms, objective='', daily_budget=None, days=30):
        valid_platforms = [p for p in platforms if p in PLATFORM_CATALOG.keys()]
        objective = objective if objective in OBJECTIVE_CATALOG else self.recommended_objective(organization).value
        weights = PLATFORM_WEIGHTS[UnifiedObjective(objective)]

        recommended_total = 100 if len(valid_platforms) >= 3 else 50 * max(1, len(valid_platforms))
        total = int(daily_budget) if daily_budget else recommended_total
        total = max(len(valid_platforms), total)
        days = max(1, int(days or 30))

        split = self.split_budget(valid_platforms, total, weights)
        cost = COST_PER_RESULT[UnifiedObjective(objective)]
        results = Decimal(total) / cost
        reach_per_dollar = 4500  # ~450K reach for $100/day
        reach_mid = total * reach_per_dollar
        return {
            'objective': objective,
            'recommended_daily_budget': recommended_total,
            'daily_budget': total,
            'currency': 'USD',
            'days': days,
            'total_spend': total * days,
            'split': split,
            'estimated_results': {
                'reach_min': int(reach_mid),
                'reach_max': int(reach_mid * 2),
                'reach_label': f"{format_count(reach_mid)} – {format_count(reach_mid * 2)}",
                'conversions_min': int(results * Decimal('0.6')),
                'conversions_max': int(results * Decimal('1.2')),
                'cost_per_result': str(_currency(cost)),
            },
            'highlights': [
                'Optimal spend for your audience',
                'Balanced across platforms',
                'Maximizes potential results',
            ],
            'presets': BUDGET_PRESETS,
        }

    @staticmethod
    def split_budget(platforms, total, weights):
        """Whole-dollar split that always sums to `total`."""
        if not platforms:
            return []
        raw = {p: weights.get(Platform(p), 1) for p in platforms}
        weight_sum = sum(raw.values())
        shares = {p: int(total * w / weight_sum) for p, w in raw.items()}
        leftover = total - sum(shares.values())
        for p in sorted(raw, key=lambda k: -raw[k]):
            if leftover <= 0:
                break
            shares[p] += 1
            leftover -= 1
        return [
            {'platform': p, 'daily_budget': shares[p], 'percent': round(shares[p] * 100 / total) if total else 0}
            for p in platforms
        ]

    # ------------------------------------------------------------ audience
    INTEREST_SUGGESTIONS = ['E-commerce', 'Marketing', 'Entrepreneurship', 'Mobile Apps', 'AI Tools', 'Fitness', 'Travel', 'Fashion']

    def audience_insights(self, reach_min, reach_max, data):
        """Classify an estimated reach range and explain it."""
        t = REACH_THRESHOLDS
        if reach_max < t['too_specific_below'] * 2 and reach_min < t['too_specific_below']:
            level = 'too_specific'
        elif reach_min > t['too_broad_above']:
            level = 'too_broad'
        else:
            level = 'optimal'

        interests = [k for k in (data.get('keywords') or '').split(',') if k.strip()]
        span = data['max_age'] - data['min_age']
        insights = [
            {'label': 'Good audience size', 'ok': level == 'optimal'},
            {'label': 'Balanced demographics', 'ok': span >= 10},
            {'label': 'High potential reach', 'ok': reach_max >= t['optimal_min']},
            {'label': 'Relevant interests selected', 'ok': len(interests) > 0},
        ]
        headline = {
            'optimal': 'Great audience!',
            'too_specific': 'Audience is too narrow',
            'too_broad': 'Audience is too broad',
        }[level]
        return {
            'level': level,
            'headline': headline,
            'insights': insights,
            'thresholds': t,
            'interest_suggestions': [
                s for s in self.INTEREST_SUGGESTIONS if s.lower() not in {i.strip().lower() for i in interests}
            ],
        }

    # ---------------------------------------------------------- creative score
    @staticmethod
    def creative_score(data):
        headline = (data.get('headline') or '').strip()
        primary = (data.get('primary_text') or '').strip()
        description = (data.get('description') or '').strip()
        cta = (data.get('call_to_action') or '').strip()
        url = (data.get('destination_url') or '').strip()
        has_asset = bool(data.get('has_asset'))
        keywords = [k for k in (data.get('keywords') or '').split(',') if k.strip()]

        checks = [
            ('High quality image' if data.get('ad_format') != 'video' else 'High quality video', has_asset, 25),
            ('Clear value proposition', 10 <= len(headline) <= HEADLINE_MAX and len(primary) >= 20, 25),
            ('Strong call to action', bool(cta), 20),
            ('Relevant to your audience', bool(keywords) or bool(description), 15),
            ('Destination URL set', url.startswith(('http://', 'https://')), 15),
        ]
        score = sum(weight for _, ok, weight in checks if ok)
        if score >= 80:
            label, message = 'Great!', 'Your creative is highly likely to perform well.'
        elif score >= 50:
            label, message = 'Good', 'Your creative is solid — a few tweaks could lift results.'
        else:
            label, message = 'Needs work', 'Add the missing pieces to improve performance.'
        return {
            'score': score,
            'max_score': 100,
            'label': label,
            'message': message,
            'checks': [{'label': name, 'ok': ok} for name, ok, _ in checks],
        }
