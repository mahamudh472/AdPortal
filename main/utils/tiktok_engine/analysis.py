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

from analysis.models import AnalysisDaily
from main.models import PlatformCampaign

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


@transaction.atomic
def generate_tiktok_campaign_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch TikTok campaign-level daily metrics and upsert into AnalysisDaily.

    Parameters
    ----------
    integration : AdIntegration
        The TikTok integration (must have access_token and ad_account_id).
    start_date : date | None
        Start of the date range. Defaults to 30 days ago.
    end_date : date | None
        End of the date range. Defaults to yesterday.
    """
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() - timedelta(days=1)

    # Build lookup: tiktok campaign_id → (PlatformCampaign, UnifiedCampaign)
    platform_campaigns = PlatformCampaign.objects.filter(
        integration=integration,
        platform_campaign_id__isnull=False,
    ).select_related("unified_campaign")

    pc_map = {}
    for pc in platform_campaigns:
        if pc.unified_campaign:
            pc_map[pc.platform_campaign_id] = pc

    if not pc_map:
        logger.info("No TikTok platform campaigns found for %s — skipping analytics.", integration)
        return

    # Fetch daily campaign-level report
    params = {
        "advertiser_id": integration.ad_account_id,
        "report_type": "BASIC",
        "data_level": "AUCTION_CAMPAIGN",
        "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
        "metrics": json.dumps([
            "spend",
            "impressions",
            "clicks",
            "ctr",
            "cpc",
            "cpm",
            "conversion",
            "cost_per_conversion",
            "complete_payment_roas",
        ]),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "filtering": json.dumps({
            "campaign_ids": list(pc_map.keys()),
        }),
    }

    logger.info(
        "Fetching TikTok analytics for %d campaigns, %s → %s",
        len(pc_map), start_date, end_date,
    )

    rows = _tiktok_report_get(integration.access_token, params)
    logger.info("Got %d report rows from TikTok", len(rows))

    saved = 0
    for row in rows:
        dimensions = row.get("dimensions", {})
        metrics = row.get("metrics", {})

        campaign_id = str(dimensions.get("campaign_id", ""))
        stat_day = dimensions.get("stat_time_day", "")

        pc = pc_map.get(campaign_id)
        if not pc or not stat_day:
            continue

        unified = pc.unified_campaign
        row_date = datetime.strptime(stat_day, "%Y-%m-%d").date()

        spend = float(metrics.get("spend", 0))
        impressions = int(float(metrics.get("impressions", 0)))
        clicks = int(float(metrics.get("clicks", 0)))
        ctr = float(metrics.get("ctr", 0))
        cpc = float(metrics.get("cpc", 0))
        cpm = float(metrics.get("cpm", 0))
        conversions = int(float(metrics.get("conversion", 0)))
        cpa = float(metrics.get("cost_per_conversion", 0))
        roas = float(metrics.get("complete_payment_roas", 0))

        AnalysisDaily.objects.update_or_create(
            platform="TIKTOK",
            account_id=integration.ad_account_id,
            campaign_id=campaign_id,
            adgroup_id=None,
            date=row_date,
            defaults={
                "organization": integration.organization,
                "unified_campaign": unified,
                "campaign_name": unified.name,
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "ctr": ctr,
                "cpc": cpc,
                "cpm": cpm,
                "conversions": conversions,
                "cpa": cpa,
                "roas": roas,
                "device_breakdown": {},
            },
        )
        saved += 1

    logger.info("Saved %d TikTok AnalysisDaily records.", saved)


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
