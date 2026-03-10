"""
Notification helpers for AdPortal.

All public functions create Notification instances while respecting the per-user
NotificationSetting (for regular users) or AdminNotificationSettings (for staff).
WebSocket pushes are attempted but never raise — a failed WS push must not break
the calling business logic.
"""

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ws_push(notification):
    """Push a single notification over the WebSocket channel layer (best-effort)."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{notification.user_id}",
            {
                "type": "send_notification",
                "data": {
                    "id": notification.id,
                    "message": notification.message,
                    "created_at": notification.created_at.isoformat(),
                },
            },
        )
    except Exception:
        logger.exception("WebSocket push failed for notification id=%s", notification.id)


def _ws_push_bulk(notifications):
    for n in notifications:
        _ws_push(n)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def notify_user(user, message, organization=None, setting_key=None):
    """
    Create a notification for a single user, respecting their NotificationSetting.

    Args:
        user:         User instance to notify.
        message:      Human-readable notification message.
        organization: Optional Organization FK value for the notification.
        setting_key:  Field name on NotificationSetting to check before creating
                      (e.g. 'campaign_performance', 'team_activity').
                      If None the notification is always created.
    """
    from accounts.models import Notification, NotificationSetting

    if setting_key:
        ns, _ = NotificationSetting.objects.get_or_create(user=user)
        if not getattr(ns, setting_key, True):
            return

    notification = Notification.objects.create(
        user=user,
        organization=organization,
        message=message,
    )
    _ws_push(notification)


def notify_org_members(organization, message, setting_key=None, roles=None):
    """
    Bulk-create notifications for organisation members, respecting their
    NotificationSetting.

    Args:
        organization: Organization instance whose members to notify.
        message:      Notification message.
        setting_key:  NotificationSetting field name to check per user.
        roles:        List of OrganizationRole strings to include.
                      Defaults to ['OWNER', 'ADMIN'].
    """
    from accounts.models import Notification, NotificationSetting
    from main.models import OrganizationMember

    if roles is None:
        roles = ["OWNER", "ADMIN"]

    members = (
        OrganizationMember.objects
        .filter(organization=organization, role__in=roles, status="ACTIVE")
        .select_related("user")
    )

    to_create = []
    for member in members:
        if member.user is None:
            continue
        if setting_key:
            ns, _ = NotificationSetting.objects.get_or_create(user=member.user)
            if not getattr(ns, setting_key, True):
                continue
        to_create.append(
            Notification(
                user=member.user,
                organization=organization,
                message=message,
            )
        )

    if not to_create:
        return

    created = Notification.objects.bulk_create(to_create)
    _ws_push_bulk(created)


def notify_admins(message, setting_key=None):
    """
    Create notifications for all active staff users, respecting their
    AdminNotificationSettings.

    Args:
        message:     Notification message.
        setting_key: AdminNotificationSettings field name to check per admin
                     (e.g. 'new_user_signup', 'failed_payment', 'system_errors').
    """
    from accounts.models import Notification, User
    from admin_dashboard.models import AdminNotificationSettings

    admins = User.objects.filter(is_staff=True, is_active=True)

    to_create = []
    for admin in admins:
        if setting_key:
            admin_settings, _ = AdminNotificationSettings.objects.get_or_create(admin=admin)
            if not getattr(admin_settings, setting_key, True):
                continue
        to_create.append(Notification(user=admin, message=message))

    if not to_create:
        return

    created = Notification.objects.bulk_create(to_create)
    _ws_push_bulk(created)
