"""
TikTok Ads Management — Pause / Resume / Status Updates

Handles write operations against the TikTok Marketing API that mutate
existing objects (status changes, updates, deletes).
Sync / read operations live in sync_ad.py.
"""

import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


# ============================================================
# HTTP HELPERS
# ============================================================

def _headers(access_token: str) -> dict:
    return {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }


def _tiktok_post(endpoint: str, access_token: str, payload: dict) -> dict:
    """Make a POST request to the TikTok Marketing API."""
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"TikTok API error on {endpoint}: [{data.get('code')}] {data.get('message')}"
        )
    return data.get("data", {})


# ============================================================
# TOGGLE CAMPAIGN STATUS (PAUSE / RESUME)
# ============================================================

def toggle_campaign_status_on_tiktok(unified_campaign_id: int, target_status: str) -> list[dict]:
    """
    Set all TikTok objects belonging to *unified_campaign_id* to *target_status*
    ("ACTIVE" or "PAUSED").

    Updates PlatformCampaign, AdGroup, and Ad rows in the DB to match.
    Returns a list of error dicts (empty list = full success).

    TikTok operation_status values:
      ENABLE  → active / running
      DISABLE → paused
    """
    from main.models import UnifiedCampaign, PlatformCampaign

    if target_status not in ("ACTIVE", "PAUSED"):
        raise ValueError(f"target_status must be ACTIVE or PAUSED, got {target_status!r}")

    tiktok_op = "ENABLE" if target_status == "ACTIVE" else "DISABLE"
    errors: list[dict] = []

    campaign = UnifiedCampaign.objects.get(id=unified_campaign_id)

    platform_campaigns = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration__platform="TIKTOK",
    ).select_related("integration").prefetch_related("ad_groups__ads")

    for pc in platform_campaigns:
        integration = pc.integration
        advertiser_id = integration.ad_account_id
        token = integration.access_token

        # ── Campaign level ─────────────────────────────────
        if pc.platform_campaign_id:
            try:
                _tiktok_post(
                    "campaign/status/update/",
                    token,
                    {
                        "advertiser_id": advertiser_id,
                        "campaign_ids": [pc.platform_campaign_id],
                        "operation_status": tiktok_op,
                    },
                )
                pc.status = target_status
                pc.save(update_fields=["status"])
                logger.info("TikTok campaign %s set to %s", pc.platform_campaign_id, tiktok_op)
            except Exception as exc:
                logger.error("Failed to update TikTok campaign %s: %s", pc.platform_campaign_id, exc)
                errors.append({"stage": "CAMPAIGN", "id": pc.platform_campaign_id, "error": str(exc)})

        # ── Ad Group level ─────────────────────────────────
        for ag in pc.ad_groups.all():
            if ag.platform_adgroup_id:
                try:
                    _tiktok_post(
                        "adgroup/status/update/",
                        token,
                        {
                            "advertiser_id": advertiser_id,
                            "adgroup_ids": [ag.platform_adgroup_id],
                            "operation_status": tiktok_op,
                        },
                    )
                    ag.status = target_status
                    ag.save(update_fields=["status"])
                except Exception as exc:
                    logger.error("Failed to update TikTok ad group %s: %s", ag.platform_adgroup_id, exc)
                    errors.append({"stage": "ADGROUP", "id": ag.platform_adgroup_id, "error": str(exc)})

            # ── Ad level ───────────────────────────────────
            for ad in ag.ads.all():
                if ad.platform_ad_id:
                    try:
                        _tiktok_post(
                            "ad/status/update/",
                            token,
                            {
                                "advertiser_id": advertiser_id,
                                "ad_ids": [ad.platform_ad_id],
                                "operation_status": tiktok_op,
                            },
                        )
                        ad.status = target_status
                        ad.save(update_fields=["status"])
                    except Exception as exc:
                        logger.error("Failed to update TikTok ad %s: %s", ad.platform_ad_id, exc)
                        errors.append({"stage": "AD", "id": ad.platform_ad_id, "error": str(exc)})

    return errors
