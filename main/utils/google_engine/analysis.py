"""
Google Ads Analytics — Fetch daily performance data and save to AnalysisDaily.

Uses Google Ads REST API v18 (GAQL search):
  POST /customers/{cid}/googleAds:search

Docs: https://developers.google.com/google-ads/api/docs/reporting/overview

Metric notes:
  - all_conversions / conversions → Google's conversion count
  - value_per_conversion → used to derive ROAS
  - cost_micros → spend in micros (divide by 1,000,000 for currency)
  - average_cpc / average_cpm → in micros as well
  - ctr → already a fraction (multiply by 100 for %)
  - segments.date → YYYY-MM-DD daily breakdown
"""

import logging
from datetime import date, timedelta, datetime

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analysis.models import AnalysisDaily
from main.models import PlatformCampaign

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_VERSION = (
    str(getattr(settings, "GOOGLE_ADS_API_VERSION", "v18"))
    .strip().strip('"').strip("'")
)
if not GOOGLE_ADS_API_VERSION.startswith("v"):
    GOOGLE_ADS_API_VERSION = f"v{GOOGLE_ADS_API_VERSION}"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"


# ============================================================
# HTTP / AUTH HELPERS  (local copies to avoid circular imports)
# ============================================================

def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "Content-Type": "application/json",
    }


def _customer_id(integration) -> str:
    return str(integration.ad_account_id).replace("-", "")


def _get_valid_token(integration) -> str:
    """Return a valid access token, refreshing if expired or close to expiry."""
    from datetime import timedelta
    if integration.token_expires_at and timezone.now() >= (
        integration.token_expires_at - timedelta(minutes=5)
    ):
        from main.utils.google_engine.sync_ad import _refresh_access_token
        return _refresh_access_token(integration)
    return integration.access_token


def _google_search(cid: str, access_token: str, query: str) -> list[dict]:
    """
    Execute a GAQL search query, handling pagination via nextPageToken.
    Returns a flat list of result rows.
    """
    url = f"{GOOGLE_ADS_BASE_URL}/customers/{cid}/googleAds:search"
    all_rows = []
    page_token = None

    while True:
        payload = {"query": query, "pageSize": 1000}
        if page_token:
            payload["pageToken"] = page_token

        resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=60)
        if not resp.ok:
            raise RuntimeError(
                f"Google Ads search failed [{resp.status_code}]: {resp.text}"
            )

        data = resp.json()
        rows = data.get("results", [])
        all_rows.extend(rows)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return all_rows


# ============================================================
# CAMPAIGN-LEVEL ANALYTICS
# ============================================================

@transaction.atomic
def generate_google_campaign_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch Google Ads campaign-level daily performance metrics and upsert
    into AnalysisDaily.

    Parameters
    ----------
    integration : AdIntegration
        The Google integration (must have access_token and ad_account_id).
    start_date : date | None
        Start of the date range. Defaults to 30 days ago.
    end_date : date | None
        End of the date range. Defaults to yesterday.
    """
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() - timedelta(days=1)

    # Build lookup: google campaign_id → PlatformCampaign
    platform_campaigns = PlatformCampaign.objects.filter(
        integration=integration,
        platform_campaign_id__isnull=False,
    ).select_related("unified_campaign")

    pc_map = {}
    for pc in platform_campaigns:
        if pc.unified_campaign:
            pc_map[pc.platform_campaign_id] = pc

    if not pc_map:
        logger.info(
            "No Google platform campaigns found for %s — skipping analytics.",
            integration,
        )
        return

    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    # Format dates for GAQL
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # Build GAQL campaign_id IN clause
    id_list = ", ".join(pc_map.keys())

    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            segments.date,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.ctr,
            metrics.average_cpc,
            metrics.average_cpm,
            metrics.conversions,
            metrics.cost_per_conversion,
            metrics.value_per_conversion,
            campaign_budget.amount_micros,
            campaign_budget.type
        FROM campaign
        WHERE campaign.id IN ({id_list})
          AND segments.date BETWEEN '{start_str}' AND '{end_str}'
          AND campaign.status != 'REMOVED'
        ORDER BY campaign.id, segments.date
    """

    logger.info(
        "Fetching Google analytics for %d campaigns, %s → %s",
        len(pc_map), start_str, end_str,
    )

    rows = _google_search(cid, token, query)
    logger.info("Got %d report rows from Google Ads", len(rows))

    # Fetch budget info once per campaign for budget_type / budget_amount
    budget_info = _fetch_campaign_budgets(cid, token, list(pc_map.keys()))

    saved = 0
    for row in rows:
        c = row.get("campaign", {})
        seg = row.get("segments", {})
        m = row.get("metrics", {})

        campaign_id = str(c.get("id", ""))
        stat_day = seg.get("date", "")

        pc = pc_map.get(campaign_id)
        if not pc or not stat_day:
            continue

        unified = pc.unified_campaign

        try:
            row_date = datetime.strptime(stat_day, "%Y-%m-%d").date()
        except ValueError:
            continue

        # Cost: micros → currency units
        cost_micros = int(m.get("costMicros", 0) or 0)
        spend = cost_micros / 1_000_000

        impressions = int(m.get("impressions", 0) or 0)
        clicks = int(m.get("clicks", 0) or 0)
        # ctr from Google is a decimal fraction (e.g. 0.05 = 5%)
        ctr = float(m.get("ctr", 0) or 0) * 100
        # average_cpc / average_cpm also in micros
        cpc_micros = int(m.get("averageCpc", 0) or 0)
        cpm_micros = int(m.get("averageCpm", 0) or 0)
        cpc = cpc_micros / 1_000_000
        cpm = cpm_micros / 1_000_000

        conversions = float(m.get("conversions", 0) or 0)
        cpa_micros = int(m.get("costPerConversion", 0) or 0)
        cpa = cpa_micros / 1_000_000

        # ROAS: (value_per_conversion * conversions) / spend
        value_per_conv = float(m.get("valuePerConversion", 0) or 0)
        total_value = value_per_conv * conversions
        roas = (total_value / spend) if spend > 0 else 0.0

        # Budget metadata for this campaign
        binfo = budget_info.get(campaign_id, {})
        budget_type = binfo.get("budget_type")
        budget_amount = binfo.get("budget_amount")

        AnalysisDaily.objects.update_or_create(
            platform="GOOGLE",
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
                "conversions": int(conversions),
                "cpa": cpa,
                "roas": roas,
                "device_breakdown": {},
                "budget_type": budget_type,
                "budget_amount": budget_amount,
            },
        )
        saved += 1

    logger.info("Saved %d Google AnalysisDaily records (campaign level).", saved)


# ============================================================
# AD GROUP-LEVEL ANALYTICS
# ============================================================

@transaction.atomic
def generate_google_adgroup_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch Google Ads ad-group-level daily performance metrics and upsert
    into AnalysisDaily (with adgroup_id populated).

    Parameters
    ----------
    integration : AdIntegration
        The Google integration.
    start_date : date | None
        Defaults to 30 days ago.
    end_date : date | None
        Defaults to yesterday.
    """
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() - timedelta(days=1)

    platform_campaigns = PlatformCampaign.objects.filter(
        integration=integration,
        platform_campaign_id__isnull=False,
    ).select_related("unified_campaign")

    pc_map = {
        pc.platform_campaign_id: pc
        for pc in platform_campaigns
        if pc.unified_campaign
    }
    if not pc_map:
        return

    cid = _customer_id(integration)
    token = _get_valid_token(integration)

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    id_list = ", ".join(pc_map.keys())

    query = f"""
        SELECT
            campaign.id,
            ad_group.id,
            ad_group.name,
            segments.date,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.ctr,
            metrics.average_cpc,
            metrics.average_cpm
        FROM ad_group
        WHERE campaign.id IN ({id_list})
          AND segments.date BETWEEN '{start_str}' AND '{end_str}'
          AND ad_group.status != 'REMOVED'
        ORDER BY campaign.id, ad_group.id, segments.date
    """

    rows = _google_search(cid, token, query)
    logger.info("Got %d ad-group report rows from Google Ads", len(rows))

    saved = 0
    for row in rows:
        c = row.get("campaign", {})
        ag = row.get("adGroup", {})
        seg = row.get("segments", {})
        m = row.get("metrics", {})

        campaign_id = str(c.get("id", ""))
        adgroup_id = str(ag.get("id", ""))
        stat_day = seg.get("date", "")

        pc = pc_map.get(campaign_id)
        if not pc or not stat_day or not adgroup_id:
            continue

        unified = pc.unified_campaign

        try:
            row_date = datetime.strptime(stat_day, "%Y-%m-%d").date()
        except ValueError:
            continue

        cost_micros = int(m.get("costMicros", 0) or 0)
        spend = cost_micros / 1_000_000
        impressions = int(m.get("impressions", 0) or 0)
        clicks = int(m.get("clicks", 0) or 0)
        ctr = float(m.get("ctr", 0) or 0) * 100
        cpc = int(m.get("averageCpc", 0) or 0) / 1_000_000
        cpm = int(m.get("averageCpm", 0) or 0) / 1_000_000

        AnalysisDaily.objects.update_or_create(
            platform="GOOGLE",
            account_id=integration.ad_account_id,
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
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
                "conversions": 0,
                "cpa": 0,
                "roas": 0,
                "device_breakdown": {},
            },
        )
        saved += 1

    logger.info("Saved %d Google AnalysisDaily records (ad-group level).", saved)


# ============================================================
# HELPER: FETCH BUDGET METADATA PER CAMPAIGN
# ============================================================

def _fetch_campaign_budgets(cid: str, access_token: str, campaign_ids: list[str]) -> dict:
    """
    Return a dict keyed by campaign_id with budget_type and budget_amount (currency).

    budget_type: "DAILY" | "LIFETIME"
    budget_amount: float (in currency units, e.g. USD)
    """
    if not campaign_ids:
        return {}

    id_list = ", ".join(campaign_ids)
    query = f"""
        SELECT
            campaign.id,
            campaign_budget.amount_micros,
            campaign_budget.type
        FROM campaign
        WHERE campaign.id IN ({id_list})
          AND campaign.status != 'REMOVED'
    """

    rows = _google_search(cid, access_token, query)

    result = {}
    for row in rows:
        c = row.get("campaign", {})
        b = row.get("campaignBudget", {})
        cid_str = str(c.get("id", ""))
        if not cid_str:
            continue

        micros = int(b.get("amountMicros", 0) or 0)
        amount = micros / 1_000_000
        btype_raw = b.get("type", "STANDARD")
        btype = "LIFETIME" if "FIXED" in str(btype_raw).upper() else "DAILY"

        result[cid_str] = {
            "budget_type": btype,
            "budget_amount": amount,
        }

    return result
