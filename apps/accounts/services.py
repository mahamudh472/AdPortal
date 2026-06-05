"""
accounts/services.py
~~~~~~~~~~~~~~~~~~~~
Business-logic layer for account-related operations.

Views should stay thin HTTP adapters; all non-trivial logic belongs here.
"""

import base64
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


def resolve_users_by_facebook_uid(facebook_uid: str) -> set:
    """
    Find all local User instances that are linked to the given Facebook UID.

    Meta may store the UID as:
      - The raw UID in ad_account_id (rare)
      - "act_<UID>" in ad_account_id (ad-account format)
      - The UID in page_id

    Args:
        facebook_uid: The Facebook user ID extracted from the signed_request.

    Returns:
        A (possibly empty) set of User instances to clean up.
    """
    from apps.main.models import AdIntegration

    users: set = set()

    meta_integrations = (
        AdIntegration.objects.filter(platform="META")
        .select_related("organization__owner")
    )

    for integration in meta_integrations:
        if (
            integration.ad_account_id == facebook_uid
            or integration.ad_account_id == f"act_{facebook_uid}"
            or integration.page_id == facebook_uid
        ):
            users.add(integration.organization.owner)

    return users


def handle_meta_data_deletion(signed_request: str) -> dict:
    """
    Orchestrate the full Meta Data Deletion Callback flow.

    Steps:
      1. Verify META_APP_SECRET is configured.
      2. Verify the signed_request signature.
      3. Extract the Facebook user ID from the payload.
      4. Resolve and delete all matching local users' data.
      5. Return the confirmation envelope Meta requires.

    Args:
        signed_request: The raw signed_request string posted by Meta.

    Returns:
        A dict with "url" and "confirmation_code" ready to be returned as JSON.

    Raises:
        MetaAppSecretNotConfigured: If META_APP_SECRET is absent in settings.
        MetaSignedRequestMissing:   If signed_request is empty / None.
        MetaSignedRequestInvalid:   If the signature cannot be verified.
    """
    if not signed_request:
        raise MetaSignedRequestMissing("signed_request field is required.")

    app_secret = getattr(settings, "META_APP_SECRET", None)
    if not app_secret:
        raise MetaAppSecretNotConfigured("META_APP_SECRET is not configured on the server.")

    payload = parse_meta_signed_request(signed_request, app_secret)

    facebook_uid: str = payload.get("user_id", "")
    if not facebook_uid:
        raise MetaSignedRequestInvalid("No user_id found in signed_request payload.")

    users = resolve_users_by_facebook_uid(facebook_uid)

    if users:
        for user in users:
            delete_all_user_data(user)
    else:
        logger.warning(
            "[MetaDataDeletion] No local user found for Facebook UID %s. "
            "Acknowledging deletion request without local changes.",
            facebook_uid,
        )

    confirmation_code = uuid.uuid4().hex[:16].upper()
    frontend_url = getattr(settings, "FRONTEND_URL", "")
    status_url = f"{frontend_url}/data-deletion?code={confirmation_code}"

    return {
        "url": status_url,
        "confirmation_code": confirmation_code,
    }
