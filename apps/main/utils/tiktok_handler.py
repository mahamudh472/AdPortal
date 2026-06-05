import requests, datetime, json, os
import hashlib
from io import BytesIO
from django.conf import settings
from django.utils import timezone
from datetime import datetime, timezone as dt_timezone
from dotenv import load_dotenv
from PIL import Image
load_dotenv()

from apps.main.models import Ad, AdAsset, PlatformAsset, PlatformCampaign

# Default to TikTok Business API (production OAuth flow).
BASE_URL = getattr(
    settings,
    "TIKTOK_API_BASE_URL",
    "https://business-api.tiktok.com/open_api/v1.3",
)
PRODUCTION_URL = "https://business-api.tiktok.com/open_api/v1.3"

# PASTE YOUR CREDENTIALS HERE
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ADVERTISER_ID = os.getenv('ADVERTISER_ID')

# Standard Headers for every request
HEADERS = {
    "Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}


def _tiktok_post(endpoint: str, access_token: str, payload: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.post(
        url,
        headers={"Access-Token": access_token, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    data = resp.json()
    if resp.status_code >= 400 or data.get("code") != 0:
        raise ValueError(
            f"TikTok {endpoint} failed [{data.get('code')}]: {data.get('message', 'Unknown error')}"
        )
    return data.get("data", {})


def _tiktok_get(endpoint: str, access_token: str, params: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(
        url,
        headers={"Access-Token": access_token},
        params=params,
        timeout=30,
    )
    data = resp.json()
    if resp.status_code >= 400 or data.get("code") != 0:
        raise ValueError(
            f"TikTok {endpoint} failed [{data.get('code')}]: {data.get('message', 'Unknown error')}"
        )
    return data.get("data", {})


def _resolve_tiktok_identity_id(integration) -> str:
    """Fetch one usable identity_id for the advertiser account."""
    data = _tiktok_get(
        "identity/get/",
        integration.access_token,
        {"advertiser_id": integration.ad_account_id},
    )

    identities = data.get("list") or []
    if not identities:
        raise ValueError(
            "TikTok identity is missing for this ad account. Please create/connect an identity in TikTok Ads Manager first."
        )

    first = identities[0] or {}
    identity_id = first.get("identity_id")
    if not identity_id:
        raise ValueError(
            "TikTok returned identities but none has identity_id. Please verify identity setup in TikTok Ads Manager."
        )
    return str(identity_id)


def _normalize_tiktok_cta(raw_cta: str | None) -> str:
    value = (raw_cta or "LEARN_MORE").upper().replace(" ", "_").strip()
    mapping = {
        "READ_MORE": "LEARN_MORE",
        "GET_STARTED": "LEARN_MORE",
        "SIGNUP": "SIGN_UP",
        "REGISTER": "SIGN_UP",
    }
    return mapping.get(value, value)


def _ensure_local_ad(platform_campaign, adgroup) -> Ad:
    local_ad = adgroup.ads.order_by("-id").first()
    if local_ad:
        return local_ad

    return Ad.objects.create(
        ad_group=adgroup,
        name=f"{platform_campaign.unified_campaign.name} - TikTok Ad",
        headline=platform_campaign.unified_campaign.name,
        primary_text="Auto-created TikTok ad",
        description="",
        destination_url="https://example.com",
        call_to_action="LEARN_MORE",
    )


def _attach_campaign_draft_asset(local_ad: Ad, campaign) -> None:
    """Attach campaign draft asset to local ad when ad has no assets yet."""
    if local_ad.assets.exists():
        return

    draft_asset_id = (campaign.draft_data or {}).get("ad_asset_id")
    if not draft_asset_id:
        return

    asset = AdAsset.objects.filter(
        id=draft_asset_id,
        organization=campaign.organization,
    ).first()
    if asset:
        local_ad.assets.add(asset)


def _upload_tiktok_asset(local_ad: Ad, integration) -> tuple[str, str] | tuple[None, None]:
    """Upload first local asset and return (ad_format, asset_id)."""
    asset = local_ad.assets.order_by("-id").first()
    if not asset:
        return None, None

    existing = PlatformAsset.objects.filter(asset=asset, integration=integration).first()
    if existing:
        if asset.file_type == "VIDEO":
            return "SINGLE_VIDEO", existing.platform_asset_id
        return "SINGLE_IMAGE", existing.platform_asset_id

    upload_headers = {"Access-Token": integration.access_token}
    if asset.file_type == "VIDEO":
        endpoint = f"{BASE_URL}/file/video/ad/upload/"
        field_name = "video_file"
        ad_format = "SINGLE_VIDEO"
    else:
        endpoint = f"{BASE_URL}/file/image/ad/upload/"
        field_name = "image_file"
        ad_format = "SINGLE_IMAGE"


    signature = None
    upload_filename = os.path.basename(asset.file.path)
    upload_content_type = "application/octet-stream"
    upload_file_bytes: bytes = b""

    if asset.file_type == "IMAGE":
        with open(asset.file.path, "rb") as image_file:
            raw_bytes = image_file.read()

        # TikTok image upload is stricter about WEBP in some accounts.
        # Convert WEBP to JPEG in memory so the multipart payload is accepted.
        if asset.file.name.lower().endswith(".webp"):
            converted = BytesIO()
            with Image.open(BytesIO(raw_bytes)) as image:
                rgb_image = image.convert("RGB")
                rgb_image.save(converted, format="JPEG", quality=95)
            upload_file_bytes = converted.getvalue()
            upload_filename = os.path.splitext(upload_filename)[0] + ".jpg"
            upload_content_type = "image/jpeg"
        else:
            upload_file_bytes = raw_bytes
            upload_content_type = "image/" + os.path.splitext(upload_filename)[1].lstrip(".").lower()

        hasher = hashlib.md5()
        hasher.update(upload_file_bytes)
        signature = hasher.hexdigest()

    # Some TikTok accounts are strict about multipart field names.
    upload_attempts = [field_name]
    if asset.file_type == "IMAGE":
        upload_attempts.append("file")

    last_data = None
    for upload_field in upload_attempts:
        if asset.file_type == "IMAGE":
            files = {upload_field: (upload_filename, BytesIO(upload_file_bytes), upload_content_type)}
        else:
            with open(asset.file.path, "rb") as f:
                files = {upload_field: (os.path.basename(asset.file.path), f, "video/mp4")}

        data_payload = {
            "advertiser_id": integration.ad_account_id,
            "upload_type": "UPLOAD_BY_FILE",
        }
        if signature:
            data_payload["image_signature"] = signature

        resp = requests.post(
            endpoint,
            headers=upload_headers,
            data=data_payload,
            files=files,
            timeout=60,
        )

        try:
            data = resp.json()
        except Exception:
            data = {"code": None, "message": resp.text}

        last_data = data
        if resp.status_code < 400 and data.get("code") == 0:
            break
    else:
        raise ValueError(
            f"TikTok asset upload failed [{(last_data or {}).get('code')}]: "
            f"{(last_data or {}).get('message', 'Unknown error')}"
        )

    if asset.file_type == "VIDEO":
        platform_asset_id = data.get("data", {}).get("video_id")
    else:
        platform_asset_id = data.get("data", {}).get("image_id")

    if not platform_asset_id:
        raise ValueError("TikTok asset upload succeeded but no platform asset id was returned")

    PlatformAsset.objects.update_or_create(
        asset=asset,
        integration=integration,
        defaults={"platform_asset_id": platform_asset_id},
    )
    asset.status = "UPLOADED"
    asset.file_hash = platform_asset_id
    asset.save(update_fields=["status", "file_hash"])

    return ad_format, platform_asset_id


def _select_platform_campaign(campaign, integration):
    """Pick one local PlatformCampaign deterministically if duplicates exist."""
    qs = PlatformCampaign.objects.filter(
        unified_campaign=campaign,
        integration=integration,
    ).order_by('-updated_at', '-id')

    selected = qs.filter(platform_campaign_id__isnull=False).first() or qs.first()
    if not selected:
        raise ValueError("No local PlatformCampaign found for this campaign/integration")
    return selected

def to_tiktok_datetime(dt):
    """
    Convert a Python datetime to TikTok Ads API format (UTC).
    Output format: YYYY-MM-DD HH:MM:SS
    """
    if dt is None:
        return None

    # Ensure datetime is timezone-aware and in UTC
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    else:
        dt = dt.astimezone(dt_timezone.utc)

    return dt.strftime("%Y-%m-%d %H:%M:%S")

def get_tiktok_adgroup_config(objective):
    # Standard settings for accounts WITHOUT a pixel
    
    if objective == "TRAFFIC":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "CLICK",   # Must be CLICK for Traffic
            "billing_event": "CPC",        # Must be CPC for CLICK
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "AWARENESS":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "REACH",   # Must be REACH for Awareness
            "billing_event": "CPM",        # Must be CPM for REACH
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "VIDEO_VIEW":
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "VIDEO_VIEW", # Must be VIDEO_VIEW
            "billing_event": "CPM",           # Must be CPM for Video Views
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    if objective == "ENGAGEMENT":
        # If campaign is 'COMMUNITY_INTERACTION', use this:
        return {
            "promotion_type": "WEBSITE",
            "optimization_goal": "CLICK",  # Without pixel, optimize for clicks
            "billing_event": "CPC",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        }

    # If it's anything else, fallback to Traffic settings to prevent crashes
    return {
        "promotion_type": "WEBSITE",
        "optimization_goal": "CLICK",
        "billing_event": "CPC",
        "bid_type": "BID_TYPE_NO_BID",
        "pacing": "PACING_MODE_SMOOTH",
    }


def _map_tiktok_campaign_objective(unified_objective: str) -> str:
    """
    Map internal objective to TikTok-compatible campaign objective for test flow.

    For accounts without conversion setup/pixel, keeping objective on TRAFFIC avoids
    strict optimization constraints that fail adgroup creation.
    """
    if unified_objective == "TRAFFIC":
        return "TRAFFIC"
    if unified_objective == "AWARENESS":
        return "REACH"
    # CONVERSIONS / LEAD_GENERATION / APP_PROMOTION / ENGAGEMENT
    # fallback to TRAFFIC in test mode
    return "TRAFFIC"

def create_platform_campaign_for_tiktok(
    campaign,
    integration,
    ADVERTISER_ID,
    ACCESS_TOKEN,
    force_recreate=False,
):
    platform_campaign = _select_platform_campaign(campaign, integration)
    campaign_budget = campaign.campaignbudget_set.filter(platform='TIKTOK').first()
    if not campaign_budget:
        raise ValueError("TikTok budget is missing for this campaign")

    if platform_campaign.platform_campaign_id and not force_recreate:
        return platform_campaign.platform_campaign_id
    
    url = f"{BASE_URL}/campaign/create/"
    if not ADVERTISER_ID:
        raise ValueError("TikTok advertiser_id (ad_account_id) is missing in integration")
    if not ACCESS_TOKEN:
        raise ValueError("TikTok access_token is missing in integration")

    headers = {
        "Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    campaign_names = [campaign.name]
    if force_recreate:
        campaign_names = [
            f"{campaign.name} [test]",
            f"{campaign.name} [test] {timezone.now().strftime('%Y%m%d%H%M%S%f')}",
        ]

    last_data = None
    for campaign_name in campaign_names:
        payload = {
            "advertiser_id": ADVERTISER_ID,
            "campaign_name": campaign_name,
            "objective_type": _map_tiktok_campaign_objective(campaign.objective),
            "budget_mode": "BUDGET_MODE_DAY" if campaign_budget.budget_type == 'DAILY' else "BUDGET_MODE_TOTAL",
            "budget": campaign_budget.daily_budget_minor, # Minimum is usually 50 in Sandbox
        }

        res = requests.post(url, headers=headers, json=payload, timeout=30)
        data = res.json()
        last_data = data

        if res.status_code < 400 and data.get('code') == 0:
            campaign_id = data['data']['campaign_id']
            platform_campaign.platform_campaign_id = campaign_id
            platform_campaign.save()
            return campaign_id

        message = str(data.get('message', '')).lower()
        duplicate_name_error = any(
            token in message
            for token in (
                'already exists',
                'already exist',
                'duplicate',
                'name exists',
            )
        )
        if not (force_recreate and duplicate_name_error and campaign_name == campaign_names[0]):
            raise ValueError(
                f"TikTok campaign create failed [{data.get('code')}]: {data.get('message', 'Unknown error')}"
            )


    raise ValueError(
        f"TikTok campaign create failed [{(last_data or {}).get('code')}]: {(last_data or {}).get('message', 'Unknown error')}"
    )


def update_platform_campaign_for_tiktok(
    campaign,
    integration,
    ADVERTISER_ID,
    ACCESS_TOKEN,
):
    platform_campaign = _select_platform_campaign(campaign, integration)
    campaign_budget = campaign.campaignbudget_set.filter(platform='TIKTOK').first()
    if not campaign_budget:
        raise ValueError("TikTok budget is missing for this campaign")

    if not platform_campaign.platform_campaign_id:
        return create_platform_campaign_for_tiktok(
            campaign,
            integration,
            ADVERTISER_ID,
            ACCESS_TOKEN,
            force_recreate=False,
        )

    if not ADVERTISER_ID:
        raise ValueError("TikTok advertiser_id (ad_account_id) is missing in integration")
    if not ACCESS_TOKEN:
        raise ValueError("TikTok access_token is missing in integration")

    url = f"{BASE_URL}/campaign/update/"
    headers = {
        "Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_id": platform_campaign.platform_campaign_id,
        "campaign_name": campaign.name,
        "objective_type": _map_tiktok_campaign_objective(campaign.objective),
        "budget_mode": "BUDGET_MODE_DAY" if campaign_budget.budget_type == 'DAILY' else "BUDGET_MODE_TOTAL",
        "budget": campaign_budget.daily_budget_minor,
    }

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()
    if res.status_code < 400 and data.get('code') == 0:
        platform_campaign.last_synced_at = timezone.now()
        platform_campaign.save()
        return platform_campaign.platform_campaign_id

    raise ValueError(
        f"TikTok campaign update failed [{data.get('code')}]: {data.get('message', 'Unknown error')}"
    )
    

def create_ad_group_for_tiktok(campaign_id, campaign=None, integration=None, ADVERTISER_ID=None, ACCESS_TOKEN=None):
    url = f"{BASE_URL}/adgroup/create/"
    if campaign and integration:
        platform_campaign = PlatformCampaign.objects.filter(
            unified_campaign=campaign,
            integration=integration,
            platform_campaign_id=campaign_id,
        ).order_by('-updated_at', '-id').first()
    else:
        platform_campaign = PlatformCampaign.objects.filter(
            platform_campaign_id=campaign_id
        ).order_by('-updated_at', '-id').first()

    if not platform_campaign:
        raise ValueError(f"No PlatformCampaign found for campaign_id={campaign_id}")

    adgroup = platform_campaign.ad_groups.first()
    if not adgroup:
        raise ValueError("No local AdGroup found for selected PlatformCampaign")

    if adgroup.platform_adgroup_id:
        return adgroup.platform_adgroup_id

    advertiser_id = ADVERTISER_ID or (integration.ad_account_id if integration else None)
    access_token = ACCESS_TOKEN or (integration.access_token if integration else None)

    campaign_budget = platform_campaign.unified_campaign.campaignbudget_set.filter(platform='TIKTOK').first()

    if not advertiser_id:
        raise ValueError("TikTok advertiser_id (ad_account_id) is missing in integration")
    if not access_token:
        raise ValueError("TikTok access_token is missing in integration")

    headers = {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }

    # Ad Group requires stricter validation than Meta.
    # TikTok still expects schedule_start_time even for from-now schedules,
    # so always send a start time and only include an end time when present.
    # Use CampaignBudget dates if available, otherwise fall back to AdGroup times.
    if campaign_budget:
        schedule_start_date = campaign_budget.start_date
        schedule_end_date = campaign_budget.end_date
        schedule_start_time = to_tiktok_datetime(timezone.make_aware(timezone.datetime.combine(schedule_start_date, timezone.datetime.min.time())))
        if schedule_end_date:
            schedule_end_time = to_tiktok_datetime(timezone.make_aware(timezone.datetime.combine(schedule_end_date, timezone.datetime.min.time())))
        else:
            schedule_end_time = None
    else:
        schedule_start_time = to_tiktok_datetime(adgroup.start_time)
        schedule_end_time = to_tiktok_datetime(adgroup.end_time) if adgroup.end_time else None

    if campaign_budget and campaign_budget.end_date:
        schedule_type = "SCHEDULE_START_END"
        payload = {
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": adgroup.name,
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_TIKTOK"],
            "location_ids": ['6252001'],
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": 20.0,
            "schedule_type": schedule_type,
            "schedule_start_time": schedule_start_time,
            "schedule_end_time": schedule_end_time,
        }
    else:
        schedule_type = "SCHEDULE_FROM_NOW"
        payload = {
            "advertiser_id": advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": adgroup.name,
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": ["PLACEMENT_TIKTOK"],
            "location_ids": ['6252001'],
            "budget_mode": "BUDGET_MODE_DAY",
            "budget": 20.0,
            "schedule_type": schedule_type,
            "schedule_start_time": schedule_start_time,
        }
    if not platform_campaign.unified_campaign:
        raise ValueError("Selected PlatformCampaign has no linked UnifiedCampaign")

    primary_config = get_tiktok_adgroup_config(platform_campaign.unified_campaign.objective)
    fallback_configs = [
        {},
        {
            "promotion_type": "WEBSITE",
            "optimization_goal": "CLICK",
            "billing_event": "CPC",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        },
        {
            "promotion_type": "WEBSITE",
            "optimization_goal": "REACH",
            "billing_event": "CPM",
            "bid_type": "BID_TYPE_NO_BID",
            "pacing": "PACING_MODE_SMOOTH",
        },
    ]

    # Try minimal payload first, then primary config, then extra fallbacks.
    attempts = [
        {},
        primary_config,
    ] + [c for c in fallback_configs if c != primary_config and c != {}]
    last_error = None
    attempt_errors = []

    for cfg in attempts:
        req_payload = {**payload, **cfg}
        res = requests.post(url, headers=headers, json=req_payload, timeout=30)
        data = res.json()

        if res.status_code < 400 and data.get('code') == 0:
            adgroup_id = data['data']['adgroup_id']
            adgroup.platform_adgroup_id = adgroup_id
            adgroup.save()
            return adgroup_id

        last_error = data
        attempt_errors.append({
            "optimization_goal": cfg.get("optimization_goal"),
            "billing_event": cfg.get("billing_event"),
            "promotion_type": cfg.get("promotion_type"),
            "code": data.get("code"),
            "message": data.get("message"),
        })
        message = str(data.get('message', '')).lower()
        duplicate_name_error = any(
            token in message
            for token in (
                'already exists',
                'already exist',
                'duplicate',
                'name exists',
            )
        )
        if duplicate_name_error and adgroup.platform_adgroup_id:
            return adgroup.platform_adgroup_id
        if data.get('code') != 40002:
            break

    raise ValueError(
        f"TikTok adgroup create failed [{(last_error or {}).get('code')}]: "
        f"{(last_error or {}).get('message', 'Unknown error')}. "
        f"Attempts={attempt_errors}"
    )

def upload_tiktok_video(campaign, integration):
    platform_campaign = _select_platform_campaign(campaign, integration)
    adgroup = platform_campaign.ad_groups.order_by("-id").first()
    if not adgroup:
        raise ValueError("No local AdGroup found for TikTok asset upload")
    local_ad = _ensure_local_ad(platform_campaign, adgroup)
    return _upload_tiktok_asset(local_ad, integration)

def create_tiktok_ad_creative(campaign, integration, adgroup_id, ad_asset: AdAsset | None = None):
    platform_campaign = _select_platform_campaign(campaign, integration)
    adgroup = platform_campaign.ad_groups.filter(
        platform_adgroup_id=adgroup_id
    ).order_by("-id").first() or platform_campaign.ad_groups.order_by("-id").first()
    if not adgroup:
        raise ValueError("No local AdGroup found for TikTok ad creation")

    local_ad = _ensure_local_ad(platform_campaign, adgroup)
    if ad_asset:
        local_ad.assets.add(ad_asset)
    _attach_campaign_draft_asset(local_ad, campaign)
    ad_format, platform_asset_id = _upload_tiktok_asset(local_ad, integration)
    identity_id = _resolve_tiktok_identity_id(integration)

    safe_ad_name = (local_ad.name or "").strip() or f"{campaign.name} - TikTok Ad"

    creative = {
        "ad_name": safe_ad_name,
        "ad_text": local_ad.primary_text or local_ad.headline or safe_ad_name,
        "call_to_action": _normalize_tiktok_cta(local_ad.call_to_action),
        "landing_page_url": local_ad.destination_url,
        "display_name": integration.account_name or campaign.organization.name,
        "identity_id": identity_id,
    }
    if ad_format == "SINGLE_VIDEO" and platform_asset_id:
        creative["ad_format"] = "SINGLE_VIDEO"
        creative["video_id"] = platform_asset_id
    elif ad_format == "SINGLE_IMAGE" and platform_asset_id:
        creative["ad_format"] = "SINGLE_IMAGE"
        creative["image_ids"] = [platform_asset_id]
    else:
        raise ValueError(
            "No ad asset found for TikTok ad creation. Attach an image/video to the campaign ad first."
        )

    payload = {
        "advertiser_id": integration.ad_account_id,
        "adgroup_id": adgroup_id,
        "ad_name": safe_ad_name,
        "creatives": [creative],
    }
    data = _tiktok_post("ad/create/", integration.access_token, payload)
    ad_ids = data.get("ad_ids") or []
    if not ad_ids:
        raise ValueError("TikTok ad/create succeeded but no ad id was returned")

    local_ad.platform_ad_id = str(ad_ids[0])
    local_ad.status = "ACTIVE"
    local_ad.save(update_fields=["platform_ad_id", "status"])
    return local_ad

def create_full_ad_for_tiktok(
    campaign,
    integration,
    force_recreate_campaign=False,
    update_existing_campaign=False,
    ad_asset: AdAsset | None = None,
):

    if update_existing_campaign:
        campaign_id = update_platform_campaign_for_tiktok(
            campaign,
            integration,
            integration.ad_account_id,
            integration.access_token,
        )
    else:
        # TODO: Need to change to the actual values from campaign and integration
        campaign_id = create_platform_campaign_for_tiktok(
            campaign,
            integration,
            integration.ad_account_id,
            integration.access_token,
            force_recreate=force_recreate_campaign,
        )
    if not campaign_id:
        raise ValueError("TikTok campaign creation did not return campaign_id")
    adgroup_id = create_ad_group_for_tiktok(
        campaign_id,
        campaign=campaign,
        integration=integration,
        ADVERTISER_ID=integration.ad_account_id,
        ACCESS_TOKEN=integration.access_token,
    )
    if not adgroup_id:
        raise ValueError("TikTok adgroup creation did not return adgroup_id")

    local_ad = create_tiktok_ad_creative(campaign, integration, adgroup_id, ad_asset=ad_asset)
    return {
        "campaign_id": campaign_id,
        "adgroup_id": adgroup_id,
        "ad_id": local_ad.id,
        "platform_ad_id": local_ad.platform_ad_id,
    }

def create_tiktok_ad_flow():

    # --- 1. CREATE CAMPAIGN ---
    url = f"{BASE_URL}/campaign/create/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_name": "Python Sandbox Campaign 2025-12-20 6",
        "objective_type": "REACH", # Options: TRAFFIC, CONVERSIONS, REACH
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": 50.0, # Minimum is usually 50 in Sandbox
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        return
        
    campaign_id = data['data']['campaign_id']
    # campaign_id = "1851326442807426"  # Use existing campaign for testing
    # --- 2. CREATE AD GROUP (Targeting) ---
    url = f"{BASE_URL}/adgroup/create/"
    
    # Ad Group requires stricter validation than Meta
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_id": campaign_id,
        "adgroup_name": "Python AdGroup US",
        "placement_type": "PLACEMENT_TYPE_NORMAL", # Only show on TikTok app
        "placements": ["PLACEMENT_TIKTOK"],
        "location_ids": ['6252001'],  # Sandbox usually supports 'US' or 'JP'
        "budget_mode": "BUDGET_MODE_DAY",
        "budget": 20.0,
        "schedule_type": "SCHEDULE_START_END",
        "schedule_start_time": "2025-12-20 00:00:00", # Future date
        "schedule_end_time": "2025-12-30 00:00:00",
        "billing_event": "CPC",
        "bid_type": "BID_TYPE_NO_BID", # Lowest Cost strategy
        "optimization_goal": "CLICK",
        "promotion_type": "WEBSITE", 
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        return

    adgroup_id = data['data']['adgroup_id']

    # --- 3. UPLOAD VIDEO (The Hard Part) ---
    # NOTE: You must have a video file named 'ad_video.mp4' in this folder
    video_path = "ad_video.mp4" 
    
    if not os.path.exists(video_path):
        return

    # Step A: Initialize Upload to get a Signature
    url = f"{BASE_URL}/file/video/ad/upload/"
    
    # We send the file binary logic differently here
    with open(video_path, 'rb') as f:
        files = {
            'min_picture': ('ad_video.mp4', f, 'video/mp4') # 'min_picture' is weird name but required
        }
        data_payload = {
            "advertiser_id": ADVERTISER_ID,
            "upload_type": "UPLOAD_BY_FILE",
        }
        
        # Requests library handles multipart/form-data automatically if we pass 'files'
        # We DO NOT send JSON content-type here
        upload_headers = {"Access-Token": ACCESS_TOKEN} 
        
        res = requests.post(url, headers=upload_headers, data=data_payload, files=files)
        data = res.json()

    if data['code'] != 0:
        return

    video_id = data['data']['video_id']

    # --- 4. CREATE AD (Creative) ---
    url = f"{BASE_URL}/ad/create/"
    
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "adgroup_id": adgroup_id,
        "ad_name": "Python Final Ad",
        "creatives": [
            {
                "ad_format": "SINGLE_VIDEO",
                "video_id": video_id,
                "ad_text": "This is a test ad from Python!",
                "call_to_action": "LEARN_MORE",
                "landing_page_url": "https://www.google.com",
                # TikTok requires a profile image and name usually, 
                # but in Sandbox it might use defaults.
                "display_name": "Python Ad Portal"
            }
        ]
    }
    
    res = requests.post(url, headers=HEADERS, json=payload)
    data = res.json()
    
    if data['code'] != 0:
        return

    ad_id = data['data']['ad_ids'][0]

def get_campaigns():
    url = f"{BASE_URL}/campaign/get/"
    payload = {
        "advertiser_id": ADVERTISER_ID
    }
    
    res = requests.get(url, headers=HEADERS, params=payload)
    data = res.json()
    with open('tiktok_campaigns.json', 'w') as f:
        json.dump(data, f, indent=4)
    
    if data['code'] != 0:
        return
    
    campaigns = data['data']['list']
    return campaigns

def get_single_campaign(campaign_id):
    url = f"{BASE_URL}/campaign/get/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "campaign_ids": [campaign_id]
    }
    
    res = requests.get(url, headers=HEADERS, params=payload)
    data = res.json()
    
    if data['code'] != 0:
        return
    
    campaign = data['data']['list'][0]

def get_analytics(ACCESS_TOKEN=None, ADVERTISER_ID=None):
    url = f"{PRODUCTION_URL}/report/integrated/get/"
    payload = {
        "advertiser_id": ADVERTISER_ID,
        "dimensions": json.dumps(["campaign_id"]), 
        "metrics": json.dumps(["spend", "impressions", "clicks", "cpc", "ctr"]) ,
        "report_type": "BASIC",
        "start_date": "2025-12-01",
        "end_date": "2025-12-20",
        "data_level": "AUCTION_CAMPAIGN",
        "page": 1,
        "page_size": 50
    }
    HEADERS["Access-Token"] = ACCESS_TOKEN
    
    res = requests.get(url, headers=HEADERS, params=payload)


    data = res.json()
    
    if data['code'] != 0:
        return f"❌ Get Analytics Failed: {data['message']}"
    
    reports = data['data']['list']
    return reports

def get_detailed_analytics(ACCESS_TOKEN=ACCESS_TOKEN, ADVERTISER_ID=ADVERTISER_ID, target_date=None):
    """
    Returns campaign metrics including ROAS and Device Breakdown.
    Format: { 
        'Campaign Name': { 
            'campaign_id': '...',
            'total_performance': {...}, 
            'device_breakdown': {...} 
        } 
    }
    """

    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    headers = {"Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}

    # 1. Fetch campaigns
    camp_res = requests.get(f"{BASE_URL}/campaign/get/", headers=headers, params={"advertiser_id": ADVERTISER_ID})
    all_campaigns = camp_res.json().get('data', {}).get('list', [])
    
    # Map IDs to Names and filter out deleted/drafts
    valid_camps = {str(c['campaign_id']): c['campaign_name'] for c in all_campaigns 
                   if str(c.get('primary_status')).upper() not in ["DELETE", "DRAFT"]}
    
    if not valid_camps:
        return {}

    # 2. Fetch Integrated Report
    report_payload = {
        "advertiser_id": ADVERTISER_ID,
        "report_type": "BASIC",
        "data_level": "AUCTION_CAMPAIGN",
        "dimensions": json.dumps(["campaign_id", "device_system"]), 
        "metrics": json.dumps([
            "spend", "impressions", "clicks", "ctr", "cpc", "conversion_roas"
        ]),
        "start_date": target_date,
        "end_date": target_date,
        "filtering": json.dumps({"campaign_ids": list(valid_camps.keys())}),
        "page_size": 100
    }

    res = requests.get(f"{BASE_URL}/report/integrated/get/", headers=headers, params=report_payload)
    report_data = res.json().get('data', {}).get('list', [])

    # 3. Structure the Result
    final_output = {}

    # Initialize output for all valid campaigns
    for c_id, c_name in valid_camps.items():
        final_output[c_name] = {
            "campaign_id": c_id,  # <--- Added campaign_id here
            "total_performance": {
                "spend": 0.0, 
                "impressions": 0, 
                "clicks": 0, 
                "ctr": "0.00", # This is the CTR
                "cpc": 0.0, 
                "roas": 0.0
            },
            "device_breakdown": {}
        }

    # Populate with actual data
    for row in report_data:
        c_id = str(row['dimensions']['campaign_id'])
        device = row['dimensions']['device_system']
        m = row['metrics']
        
        c_name = valid_camps.get(c_id)
        if not c_name: continue

        # Add to device breakdown
        final_output[c_name]["device_breakdown"][device] = {
            "spend": m.get("spend"),
            "impressions": m.get("impressions"),
            "clicks": m.get("clicks"),
            "ctr": f"{m.get('ctr')}",
            "cpc": m.get("cpc"),
            "roas": m.get("conversion_roas")
        }
        
        # Update Total Performance
        total = final_output[c_name]["total_performance"]
        total["spend"] += float(m.get("spend", 0))
        total["impressions"] += int(m.get("impressions", 0))
        total["clicks"] += int(m.get("clicks", 0))
        
        # Recalculate Click Rate and CPC for accuracy based on totals
        if total["impressions"] > 0:
            ctr_val = (total["clicks"] / total["impressions"]) * 100
            total["ctr"] = f"{ctr_val:.2f}"
        
        if total["clicks"] > 0:
            total["cpc"] = round(total["spend"] / total["clicks"], 2)

        # ROAS is usually taken as the max value or the campaign-wide average
        total["roas"] = max(total["roas"], float(m.get("conversion_roas", 0))) 

    return final_output

if __name__ == '__main__':
    # create_tiktok_ad_flow()
    # get_campaigns()
    # get_single_campaign("7582640422065864711")
    result = get_analytics(ACCESS_TOKEN, ADVERTISER_ID)
