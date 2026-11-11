"""
accounts/services.py
~~~~~~~~~~~~~~~~~~~~
Business-logic layer for account-related operations.

Views should stay thin HTTP adapters; all non-trivial logic belongs here.
"""

import base64
import time
import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings

from .models import Notification, NotificationSetting, OTP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MetaSignedRequestError(Exception):
    """Raised when a Meta signed_request cannot be verified."""


class MetaSignedRequestMissing(MetaSignedRequestError):
    """signed_request field was not present in the request payload."""


class MetaSignedRequestInvalid(MetaSignedRequestError):
    """Signature verification failed or payload is malformed."""


class MetaAppSecretNotConfigured(Exception):
    """META_APP_SECRET is missing from Django settings."""


# ---------------------------------------------------------------------------
# Meta signed-request helpers
# ---------------------------------------------------------------------------

def _b64_decode(data: str) -> bytes:
    """URL-safe base64 decode with automatic padding."""
    data += "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data)


def parse_meta_signed_request(signed_request: str, app_secret: str) -> dict:
    """
    Decode and verify a Meta signed_request.

    Meta encodes the payload as:
        base64url(HMAC-SHA256(payload)) + "." + base64url(payload_json)

    Args:
        signed_request: The raw signed_request string from Meta.
        app_secret:     The Meta App Secret used to sign the request.

    Returns:
        The decoded payload dict.

    Raises:
        MetaSignedRequestInvalid: If the format is wrong, algorithm is
                                   unsupported, or the HMAC does not match.
    """
    try:
        encoded_sig, raw_payload = signed_request.split(".", 1)
    except ValueError:
        raise MetaSignedRequestInvalid("signed_request must contain exactly one '.' separator.")

    try:
        sig = _b64_decode(encoded_sig)
        data = json.loads(_b64_decode(raw_payload).decode("utf-8"))
    except Exception as exc:
        raise MetaSignedRequestInvalid(f"Failed to decode signed_request: {exc}") from exc

    if data.get("algorithm", "").upper() != "HMAC-SHA256":
        raise MetaSignedRequestInvalid(
            f"Unsupported signing algorithm: {data.get('algorithm')!r}. Expected HMAC-SHA256."
        )

    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        raw_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected_sig):
        raise MetaSignedRequestInvalid("HMAC signature mismatch — request may be forged.")

    return data


# ---------------------------------------------------------------------------
# Data deletion service
# ---------------------------------------------------------------------------

def delete_all_user_data(user) -> dict:
    """
    Permanently delete all platform data owned by *user*.

    Deletes:
      - All owned Organizations (cascades to Campaigns, PlatformCampaigns,
        AdGroups, Ads, AdAssets, PlatformAssets, AdIntegrations, AIInsights,
        PlatformSyncEvents, Subscriptions, Payments, UsageRecords,
        AnalysisDaily, and Reports)
      - Notifications
      - OTPs
      - NotificationSettings

    The User account record itself is **preserved**.

    Args:
        user: The User instance whose data should be deleted.

    Returns:
        A dict summarising the top-level counts that were deleted, e.g.:
        {"organizations": 2, "notifications": 14, "otps": 1, "notification_settings": 1}
    """
    # Import here to avoid circular imports at module load time.
    from apps.main.models import Organization

    summary: dict = {}

    # Organizations cascade-delete everything underneath them.
    orgs = Organization.objects.filter(owner=user)
    summary["organizations"] = orgs.count()
    orgs.delete()

    summary["notifications"], _ = Notification.objects.filter(user=user).delete()
    summary["otps"], _ = OTP.objects.filter(user=user).delete()
    summary["notification_settings"], _ = NotificationSetting.objects.filter(user=user).delete()

    logger.info(
        "Deleted all data for user %s: %s",
        user.pk,
        summary,
    )
    return summary


def delete_facebook_user_data(facebook_uid: str) -> int:
    """Delete the Meta connections that belong to this Facebook user.

    Integrations are matched on the Facebook user id stored when the account was
    connected (``AdIntegration.external_user_id``) — never on ad-account / page ids, which
    are different identifiers and could wipe another customer's data. Only the data
    received from Facebook (the integration, its tokens and everything cascading from it)
    is removed; the customer's account and organization are kept.
    """
    from apps.main.models import AdIntegration

    qs = AdIntegration.objects.filter(platform="META", external_user_id=facebook_uid)
    count = qs.count()
    qs.delete()
    return count
