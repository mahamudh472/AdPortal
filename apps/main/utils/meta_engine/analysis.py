"""
Meta (Facebook / Instagram) analytics ingestion.

Daily campaign insights go to ``AnalysisDaily``; the optional breakdowns (publisher
platform, placement, age, gender, country, device, hour of day) go to
``AnalysisBreakdownDaily``. A failing breakdown never fails the daily sync: it is
logged and reported through ``AdIntegration.analytics_error`` instead.

Docs: https://developers.facebook.com/documentation/ads-commerce/marketing-api/insights/breakdowns
Notes from the docs that shape this module:
  * ``impression_device`` (and frequency_value / audience-time-zone hourly) may need the
    account admin to opt in (Insights Feature Settings) since 2026-08-06 -> an empty
    result is reported as "device data not enabled", never fabricated.
  * Hourly breakdowns return 0 for reach/frequency and cannot be combined with video_*.
"""
import logging

from facebook_business.adobjects.campaign import Campaign

from apps.analysis.ingest import (
    default_window, extract_meta_result, mark_sync_result, parse_hour,
    replace_breakdown, safe_float, safe_int, save_daily,
)
from apps.main.models import PlatformCampaign
from .sync_ad import init_meta_api

logger = logging.getLogger(__name__)

DAILY_FIELDS = [
    "date_start", "impressions", "clicks", "spend", "reach", "frequency",
    "actions", "action_values",
]
BREAKDOWN_FIELDS = ["date_start", "impressions", "clicks", "spend", "actions", "action_values"]
# Meta's "hourly" and "device" stats are the ones that can be unavailable per account.
OPT_IN_HINT = "enable in Ads Manager (Insights settings), takes ~24h"


def _time_range(start, end):
    return {"since": start.strftime("%Y-%m-%d"), "until": end.strftime("%Y-%m-%d")}


def _row_date(row):
    from datetime import datetime
    return datetime.strptime(row["date_start"], "%Y-%m-%d").date()


def _breakdown_rows(campaign, start, end, breakdowns, objective):
    """Fetch insights with ``breakdowns`` and yield normalized dicts (raw breakdown values kept)."""
    fields = list(BREAKDOWN_FIELDS)
    params = {
        "level": "campaign",
        "time_increment": 1,
        "breakdowns": breakdowns,
        "time_range": _time_range(start, end),
        "limit": 500,
    }
    for row in campaign.get_insights(fields=fields, params=params):
        conversions, value = extract_meta_result(row, objective)
        yield {
            "raw": row,
            "date": _row_date(row),
            "impressions": safe_int(row.get("impressions")),
            "clicks": safe_int(row.get("clicks")),
            "spend": safe_float(row.get("spend")),
            "conversions": conversions,
            "conversion_value": value,
        }


def _with_key(rows, key_fn):
    for r in rows:
        key = key_fn(r["raw"])
        if key:
            yield {k: v for k, v in r.items() if k != "raw"} | {"key": key}


def sync_breakdowns(integration, platform_campaign, start, end):
    """Pull every breakdown for one campaign. Returns a list of human-readable failures."""
    unified = platform_campaign.unified_campaign
    campaign = Campaign(platform_campaign.platform_campaign_id)
    objective = unified.objective
    cid = platform_campaign.platform_campaign_id
    failures = []

    def store(dimension, rows):
        replace_breakdown(
            integration=integration, unified_campaign=unified, campaign_id=cid,
            dimension=dimension, start=start, end=end, rows=rows,
        )

    def attempt(label, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a breakdown must never break the daily sync
            logger.warning("Meta %s breakdown failed for campaign %s: %s", label, cid, exc)
            failures.append(f"{label}: {str(exc)[:120]}")

    # publisher_platform + platform_position is a valid pair -> placements and platform totals
    def placements():
        rows = list(_breakdown_rows(campaign, start, end, ["publisher_platform", "platform_position"], objective))
        store("publisher_platform", _with_key(rows, lambda r: r.get("publisher_platform")))
        store("placement", _with_key(
            rows,
            lambda r: f"{r.get('publisher_platform')}:{r.get('platform_position')}"
            if r.get("publisher_platform") and r.get("platform_position") else None,
        ))
    attempt("placements", placements)

    def demographics():
        rows = list(_breakdown_rows(campaign, start, end, ["age", "gender"], objective))
        store("age", _with_key(rows, lambda r: r.get("age")))
        store("gender", _with_key(rows, lambda r: r.get("gender")))
    attempt("age/gender", demographics)

    def country():
        rows = _breakdown_rows(campaign, start, end, ["country"], objective)
        store("country", _with_key(rows, lambda r: r.get("country")))
    attempt("country", country)

    def device():
        rows = list(_breakdown_rows(campaign, start, end, ["impression_device"], objective))
        if not rows:
            raise RuntimeError(f"no device data (account may need opt-in: {OPT_IN_HINT})")
        store("device", _with_key(rows, lambda r: r.get("impression_device")))
    attempt("device", device)

    def hourly():
        rows = _breakdown_rows(campaign, start, end, ["hourly_stats_aggregated_by_advertiser_time_zone"], objective)
        store("hour", _with_key(
            rows, lambda r: parse_hour(r.get("hourly_stats_aggregated_by_advertiser_time_zone", "")),
        ))
    attempt("hour of day", hourly)

    return failures


def generate_meta_campaign_analysis(integration, platform_campaign_ids, start_date=None, end_date=None):
    """Upsert daily insights (+ breakdowns) for the given Meta campaigns.

    Defaults to the rolling 28-day window because Meta revises recent conversions.
    """
    start, end = default_window(start_date, end_date)
    init_meta_api(integration.access_token)
    failures = []

    for campaign_id in platform_campaign_ids:
        platform_campaign = PlatformCampaign.objects.filter(
            integration=integration,
            platform_campaign_id=campaign_id,
            unified_campaign__isnull=False,
        ).select_related("unified_campaign").first()
        if not platform_campaign:
            continue

        unified = platform_campaign.unified_campaign
        campaign = Campaign(campaign_id)

        budget_type = budget_amount = None
        try:
            data = campaign.api_get(fields=["daily_budget", "lifetime_budget"])
            if data.get("daily_budget"):
                budget_type, budget_amount = "DAILY", float(data["daily_budget"]) / 100
            elif data.get("lifetime_budget"):
                budget_type, budget_amount = "LIFETIME", float(data["lifetime_budget"]) / 100
        except Exception as exc:  # noqa: BLE001
            logger.info("Meta budget lookup failed for %s: %s", campaign_id, exc)

        insights = campaign.get_insights(
            fields=DAILY_FIELDS,
            params={"level": "campaign", "time_increment": 1, "time_range": _time_range(start, end), "limit": 500},
        )
        for row in insights:
            conversions, value = extract_meta_result(row, unified.objective)
            save_daily(
                integration=integration,
                unified_campaign=unified,
                campaign_id=campaign_id,
                row_date=_row_date(row),
                impressions=safe_int(row.get("impressions")),
                clicks=safe_int(row.get("clicks")),
                spend=safe_float(row.get("spend")),
                conversions=conversions,
                conversion_value=value,
                reach=safe_int(row.get("reach"), None) if row.get("reach") is not None else None,
                frequency=safe_float(row.get("frequency"), None) if row.get("frequency") is not None else None,
                budget_type=budget_type,
                budget_amount=budget_amount,
            )

        failures += sync_breakdowns(integration, platform_campaign, start, end)

    mark_sync_result(integration, failures)
