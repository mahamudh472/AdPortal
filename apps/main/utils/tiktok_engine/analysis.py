"""
TikTok Analytics — Fetch daily performance data and save to AnalysisDaily.

Uses TikTok Reporting API v1.3:
  GET /report/integrated/get/

Docs: https://business-api.tiktok.com/marketing_api/docs?id=1740302848100353
"""

import logging
import json
from datetime import date, timedelta, datetime

import requests
from django.db import transaction

from apps.analysis.models import AnalysisDaily
from apps.main.models import PlatformCampaign

logger = logging.getLogger(__name__)

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


def _headers(access_token: str) -> dict:
    return {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }


def _tiktok_report_get(access_token: str, params: dict) -> list[dict]:
    """Call the TikTok integrated report endpoint with pagination."""
    url = f"{BASE_URL}/report/integrated/get/"
    all_rows = []
    page = 1
    page_size = 200

    while True:
        params["page"] = page
        params["page_size"] = page_size
        resp = requests.get(url, headers=_headers(access_token), params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(
                f"TikTok Report API error: [{data.get('code')}] {data.get('message')}"
            )

        rows = data.get("data", {}).get("list", [])
        all_rows.extend(rows)

        total = data.get("data", {}).get("page_info", {}).get("total_number", 0)
        if len(all_rows) >= total or not rows:
            break
        page += 1

    return all_rows


BASE_METRICS = [
    "spend", "impressions", "clicks", "ctr", "cpc", "cpm",
    "conversion", "cost_per_conversion", "complete_payment_roas",
]
# Newer/optional metrics; requested separately so an unsupported one cannot break the sync.
EXTRA_METRICS = ["reach", "frequency", "video_play_actions"]
AUDIENCE_METRICS = ["spend", "impressions", "clicks", "conversion", "complete_payment_roas"]


def _report(access_token, advertiser_id, pc_ids, dimensions, metrics, start, end, report_type="BASIC"):
    return _tiktok_report_get(access_token, {
        "advertiser_id": advertiser_id,
        "report_type": report_type,
        "data_level": "AUCTION_CAMPAIGN",
        "dimensions": json.dumps(dimensions),
        "metrics": json.dumps(metrics),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "filtering": json.dumps({"campaign_ids": list(pc_ids)}),
    })


def _fetch_daily_rows(access_token, advertiser_id, pc_ids, start, end):
    """Daily rows with the optional metrics; falls back to the base set if TikTok rejects them."""
    try:
        return _report(access_token, advertiser_id, pc_ids, ["campaign_id", "stat_time_day"],
                       BASE_METRICS + EXTRA_METRICS, start, end)
    except RuntimeError as exc:
        logger.warning("TikTok extra metrics rejected (%s); retrying with base metrics", exc)
        return _report(access_token, advertiser_id, pc_ids, ["campaign_id", "stat_time_day"],
                       BASE_METRICS, start, end)


def _tt_parts(metrics):
    spend = float(metrics.get("spend", 0) or 0)
    roas = float(metrics.get("complete_payment_roas", 0) or 0)
    return (
        int(float(metrics.get("impressions", 0) or 0)),
        int(float(metrics.get("clicks", 0) or 0)),
        spend,
        float(metrics.get("conversion", 0) or 0),
        roas * spend,  # revenue = ROAS x spend (TikTok reports the ratio)
    )


def _sync_tiktok_breakdowns(integration, pc_map, start, end):
    """Hour of day (BASIC report) + audience reports. Each isolated: failures are reported, not raised."""
    from apps.analysis.ingest import parse_hour, replace_breakdown

    token, advertiser = integration.access_token, integration.ad_account_id
    failures = []

    # (dimension, report_type, extra report dimension, response field, key transform, metrics)
    specs = [
        ("hour", "BASIC", "stat_time_hour", "stat_time_hour", parse_hour, ["spend", "impressions", "clicks", "conversion", "complete_payment_roas"]),
        ("gender", "AUDIENCE", "gender", "gender", lambda v: str(v).lower(), AUDIENCE_METRICS),
        ("age", "AUDIENCE", "age", "age", lambda v: str(v).replace("AGE_", "").replace("_", "-").lower(), AUDIENCE_METRICS),
        ("country", "AUDIENCE", "country_code", "country_code", lambda v: str(v).upper(), AUDIENCE_METRICS),
        ("device", "AUDIENCE", "platform", "platform", lambda v: str(v).lower(), AUDIENCE_METRICS),
    ]
    for dimension, report_type, dim_name, field, transform, metrics in specs:
        try:
            dims = ["campaign_id", dim_name]
            if report_type == "AUDIENCE":
                dims.append("stat_time_day")
            rows = _report(token, advertiser, pc_map.keys(), dims, metrics, start, end, report_type)
            per_campaign = {}
            for row in rows:
                d, m = row.get("dimensions", {}), row.get("metrics", {})
                campaign_id = str(d.get("campaign_id", ""))
                raw = d.get(field)
                stamp = d.get("stat_time_day") or d.get("stat_time_hour")
                if campaign_id not in pc_map or raw is None or not stamp:
                    continue
                key = transform(raw)
                if not key:
                    continue
                impressions, clicks, spend, conversions, value = _tt_parts(m)
                per_campaign.setdefault(campaign_id, []).append({
                    "date": datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date(), "key": key,
                    "impressions": impressions, "clicks": clicks, "spend": spend,
                    "conversions": conversions, "conversion_value": value,
                })
            for campaign_id, pc in pc_map.items():
                replace_breakdown(
                    integration=integration, unified_campaign=pc.unified_campaign,
                    campaign_id=campaign_id, dimension=dimension, start=start, end=end,
                    rows=per_campaign.get(campaign_id, []),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TikTok %s breakdown failed for %s: %s", dimension, integration, exc)
            failures.append(f"{dimension}: {str(exc)[:120]}")
    return failures


def generate_tiktok_campaign_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch TikTok campaign-level daily metrics (+ breakdowns) and upsert them.
    Defaults to the rolling 28-day window; revenue is ``complete_payment_roas x spend``.
    """
    from apps.analysis.ingest import default_window, mark_sync_result, save_daily

    start_date, end_date = default_window(start_date, end_date)

    pc_map = {
        pc.platform_campaign_id: pc
        for pc in PlatformCampaign.objects.filter(
            integration=integration, platform_campaign_id__isnull=False,
        ).select_related("unified_campaign")
        if pc.unified_campaign
    }
    if not pc_map:
        logger.info("No TikTok platform campaigns found for %s — skipping analytics.", integration)
        return

    rows = _fetch_daily_rows(integration.access_token, integration.ad_account_id, pc_map.keys(), start_date, end_date)
    logger.info("Got %d report rows from TikTok", len(rows))

    saved = 0
    for row in rows:
        dimensions, metrics = row.get("dimensions", {}), row.get("metrics", {})
        campaign_id = str(dimensions.get("campaign_id", ""))
        stat_day = dimensions.get("stat_time_day", "")
        pc = pc_map.get(campaign_id)
        if not pc or not stat_day:
            continue
        impressions, clicks, spend, conversions, value = _tt_parts(metrics)
        reach = metrics.get("reach")
        frequency = metrics.get("frequency")
        video = metrics.get("video_play_actions")
        save_daily(
            integration=integration,
            unified_campaign=pc.unified_campaign,
            campaign_id=campaign_id,
            row_date=datetime.strptime(str(stat_day)[:10], "%Y-%m-%d").date(),
            impressions=impressions, clicks=clicks, spend=spend,
            conversions=conversions, conversion_value=value,
            reach=int(float(reach)) if reach not in (None, "") else None,
            frequency=float(frequency) if frequency not in (None, "") else None,
            video_views=int(float(video)) if video not in (None, "") else None,
        )
        saved += 1
    logger.info("Saved %d TikTok AnalysisDaily records.", saved)

    failures = _sync_tiktok_breakdowns(integration, pc_map, start_date, end_date)
    mark_sync_result(integration, failures)


@transaction.atomic
def generate_tiktok_adgroup_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch TikTok ad-group-level daily metrics with device breakdown
    and merge into the campaign-level AnalysisDaily records.
    """
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() - timedelta(days=1)

    platform_campaigns = PlatformCampaign.objects.filter(
        integration=integration,
        platform_campaign_id__isnull=False,
    ).select_related("unified_campaign")

    campaign_ids = [pc.platform_campaign_id for pc in platform_campaigns if pc.unified_campaign]
    if not campaign_ids:
        return

    params = {
        "advertiser_id": integration.ad_account_id,
        "report_type": "BASIC",
        "data_level": "AUCTION_ADGROUP",
        "dimensions": json.dumps(["adgroup_id", "campaign_id", "stat_time_day"]),
        "metrics": json.dumps([
            "spend", "impressions", "clicks", "ctr", "cpc",
        ]),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "filtering": json.dumps({
            "campaign_ids": campaign_ids,
        }),
    }

    rows = _tiktok_report_get(integration.access_token, params)
    logger.info("Got %d ad-group report rows from TikTok", len(rows))

    # We store ad-group level data as separate AnalysisDaily rows (adgroup_id filled)
    pc_map = {pc.platform_campaign_id: pc for pc in platform_campaigns if pc.unified_campaign}

    for row in rows:
        dimensions = row.get("dimensions", {})
        metrics = row.get("metrics", {})

        campaign_id = str(dimensions.get("campaign_id", ""))
        adgroup_id = str(dimensions.get("adgroup_id", ""))
        stat_day = dimensions.get("stat_time_day", "")

        pc = pc_map.get(campaign_id)
        if not pc or not stat_day:
            continue

        unified = pc.unified_campaign
        row_date = datetime.strptime(stat_day, "%Y-%m-%d").date()

        AnalysisDaily.objects.update_or_create(
            platform="TIKTOK",
            account_id=integration.ad_account_id,
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
            date=row_date,
            defaults={
                "organization": integration.organization,
                "unified_campaign": unified,
                "campaign_name": unified.name,
                "impressions": int(float(metrics.get("impressions", 0))),
                "clicks": int(float(metrics.get("clicks", 0))),
                "spend": float(metrics.get("spend", 0)),
                "ctr": float(metrics.get("ctr", 0)),
                "cpc": float(metrics.get("cpc", 0)),
                "cpm": 0,
                "conversions": 0,
                "cpa": 0,
                "roas": 0,
                "device_breakdown": {},
            },
        )

    logger.info("Saved ad-group analytics for TikTok.")
