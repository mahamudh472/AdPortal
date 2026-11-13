"""
Google Ads Analytics — Fetch daily performance data and save to AnalysisDaily.

Uses Google Ads REST API v26 (GAQL search):
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

from apps.analysis.models import AnalysisDaily
from apps.main.models import PlatformCampaign

logger = logging.getLogger(__name__)

GOOGLE_ADS_API_VERSION = (
    str(getattr(settings, "GOOGLE_ADS_API_VERSION", "v26"))
    .strip().strip('"').strip("'")
)
if not GOOGLE_ADS_API_VERSION.startswith("v"):
    GOOGLE_ADS_API_VERSION = f"v{GOOGLE_ADS_API_VERSION}"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"


# ============================================================
# HTTP / AUTH HELPERS  (local copies to avoid circular imports)
# ============================================================

def _get_login_customer_id(access_token: str) -> str | None:
    """Resolve the login customer ID for the given access token, falling back to settings."""
    try:
        from apps.main.models import AdIntegration
        integration = AdIntegration.find_by_token(access_token)
        if integration and integration.manager_id:
            return str(integration.manager_id).replace("-", "")
    except Exception:
        pass
    
    # Fallback to settings
    if getattr(settings, "GOOGLE_ADS_USE_TEST_ACCOUNT", False):
        mid = getattr(settings, "GOOGLE_ADS_TEST_MANAGER_ID", None)
    else:
        mid = getattr(settings, "GOOGLE_ADS_MANAGER_ID", None)
    if mid:
        return str(mid).replace("-", "")
    return None


def _headers(access_token: str, login_customer_id: str | None = None) -> dict:
    if login_customer_id is None:
        login_customer_id = _get_login_customer_id(access_token)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "developer-token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        "Content-Type": "application/json",
    }
    if login_customer_id:
        headers["login-customer-id"] = str(login_customer_id).replace("-", "")
    return headers


def _customer_id(integration) -> str:
    return str(integration.ad_account_id).replace("-", "")


def _get_valid_token(integration) -> str:
    """Return a valid access token, refreshing if expired or close to expiry."""
    from datetime import timedelta
    if integration.token_expires_at and timezone.now() >= (
        integration.token_expires_at - timedelta(minutes=5)
    ):
        from apps.main.utils.google_engine.sync_ad import _refresh_access_token
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

def _gaql_in(ids):
    # Campaign ids come from our own DB, but keep the clause strictly numeric.
    return ", ".join(str(int(i)) for i in ids if str(i).isdigit())


def _micros(value):
    return int(value or 0) / 1_000_000


def _metric_parts(m):
    """(impressions, clicks, spend, conversions, conversion_value) from a GAQL metrics dict."""
    return (
        int(m.get("impressions", 0) or 0),
        int(m.get("clicks", 0) or 0),
        _micros(m.get("costMicros")),
        float(m.get("conversions", 0) or 0),
        float(m.get("conversionsValue", 0) or 0),
    )


BREAKDOWN_METRICS = (
    "metrics.impressions, metrics.clicks, metrics.cost_micros, "
    "metrics.conversions, metrics.conversions_value"
)


def _breakdown_query(select_extra, resource, id_list, start_str, end_str, extra_where=""):
    return f"""
        SELECT campaign.id, segments.date, {select_extra}, {BREAKDOWN_METRICS}
        FROM {resource}
        WHERE campaign.id IN ({id_list})
          AND segments.date BETWEEN '{start_str}' AND '{end_str}' {extra_where}
    """


def _dig(row, path):
    cur = row
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def _sync_google_breakdowns(integration, cid, token, pc_map, start, end):
    """Optional breakdowns; each is isolated so one incompatible query cannot fail the sync."""
    from apps.analysis.ingest import parse_hour, replace_breakdown

    start_str, end_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    id_list = _gaql_in(pc_map.keys())
    failures = []

    # (dimension, resource, segment/attribute field, path in the response row, key transform)
    specs = [
        ("device", "campaign", "segments.device", "segments.device", str.lower),
        ("hour", "campaign", "segments.hour", "segments.hour", parse_hour),
        ("placement", "campaign", "segments.ad_network_type", "segments.adNetworkType", str.lower),
        ("age", "age_range_view", "ad_group_criterion.age_range.type",
         "adGroupCriterion.ageRange.type", lambda v: v.replace("AGE_RANGE_", "").replace("_", "-").lower()),
        ("gender", "gender_view", "ad_group_criterion.gender.type",
         "adGroupCriterion.gender.type", str.lower),
        ("country", "geographic_view", "segments.country_localized_name",
         "segments.countryLocalizedName", lambda v: str(v).strip()[:100]),
    ]
    for dimension, resource, select_field, path, transform in specs:
        try:
            rows = _google_search(cid, token, _breakdown_query(select_field, resource, id_list, start_str, end_str))
            per_campaign = {}
            for row in rows:
                campaign_id = str(_dig(row, "campaign.id") or "")
                day = _dig(row, "segments.date")
                raw = _dig(row, path)
                if campaign_id not in pc_map or not day or raw is None:
                    continue
                key = transform(str(raw))
                if not key:
                    continue
                impressions, clicks, spend, conversions, value = _metric_parts(row.get("metrics", {}))
                per_campaign.setdefault(campaign_id, []).append({
                    "date": datetime.strptime(day, "%Y-%m-%d").date(), "key": key,
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
            logger.warning("Google %s breakdown failed for %s: %s", dimension, integration, exc)
            failures.append(f"{dimension}: {str(exc)[:120]}")
    return failures


def generate_google_campaign_analysis(
    integration,
    start_date: date | None = None,
    end_date: date | None = None,
):
    """
    Fetch Google Ads campaign-level daily metrics (+ breakdowns) and upsert them.

    Defaults to the rolling 28-day window (conversions are reported late). Revenue is
    ``metrics.conversions_value``; "conversions" is Google's ``metrics.conversions``.
    """
    from apps.analysis.ingest import default_window, mark_sync_result, save_daily

    start_date, end_date = default_window(start_date, end_date)

    platform_campaigns = PlatformCampaign.objects.filter(
        integration=integration,
        platform_campaign_id__isnull=False,
    ).select_related("unified_campaign")
    pc_map = {pc.platform_campaign_id: pc for pc in platform_campaigns if pc.unified_campaign}
    if not pc_map:
        logger.info("No Google platform campaigns found for %s — skipping analytics.", integration)
        return

    cid = _customer_id(integration)
    token = _get_valid_token(integration)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    id_list = _gaql_in(pc_map.keys())

    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            segments.date,
            {BREAKDOWN_METRICS},
            metrics.video_views
        FROM campaign
        WHERE campaign.id IN ({id_list})
          AND segments.date BETWEEN '{start_str}' AND '{end_str}'
          AND campaign.status != 'REMOVED'
        ORDER BY campaign.id, segments.date
    """
    rows = _google_search(cid, token, query)
    logger.info("Got %d report rows from Google Ads", len(rows))
    budget_info = _fetch_campaign_budgets(cid, token, list(pc_map.keys()))

    saved = 0
    for row in rows:
        campaign_id = str(row.get("campaign", {}).get("id", ""))
        stat_day = row.get("segments", {}).get("date", "")
        pc = pc_map.get(campaign_id)
        if not pc or not stat_day:
            continue
        try:
            row_date = datetime.strptime(stat_day, "%Y-%m-%d").date()
        except ValueError:
            continue

        m = row.get("metrics", {})
        impressions, clicks, spend, conversions, value = _metric_parts(m)
        binfo = budget_info.get(campaign_id, {})
        save_daily(
            integration=integration,
            unified_campaign=pc.unified_campaign,
            campaign_id=campaign_id,
            row_date=row_date,
            impressions=impressions,
            clicks=clicks,
            spend=spend,
            conversions=conversions,
            conversion_value=value,
            video_views=int(float(m.get("videoViews", 0) or 0)),
            budget_type=binfo.get("budget_type"),
            budget_amount=binfo.get("budget_amount"),
        )
        saved += 1
    logger.info("Saved %d Google AnalysisDaily records (campaign level).", saved)

    failures = _sync_google_breakdowns(integration, cid, token, pc_map, start_date, end_date)
    mark_sync_result(integration, failures)


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
