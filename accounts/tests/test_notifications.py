"""
Tests for notification endpoints:
  GET  /accounts/notifications/
  POST /accounts/read-notification/
  POST /accounts/read-all-notifications/
  POST /accounts/delete-notification/
  POST /accounts/delete-all-notifications/
  GET  /accounts/notification-settings/
  PATCH /accounts/notification-settings/
  POST /accounts/test-notifications/
"""
from django.urls import reverse

from accounts.models import Notification
from accounts.tests.base import AdPortalTestBase


class NotificationListTests(AdPortalTestBase):
    """Tests for GET /accounts/notifications/"""

    def _url(self):
        return reverse("notifications")

    def _make_notification(self, user, message="Test", read=False):
        return Notification.objects.create(user=user, message=message, read=read)

    def test_list_notifications_returns_200_with_unread_count(self):
        user = self.create_user(email="notif@example.com")
        self._make_notification(user, "Msg 1", read=False)
        self._make_notification(user, "Msg 2", read=True)
        self.authenticate(user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["unread_count"], 1)

    def test_list_notifications_empty(self):
        user = self.create_user(email="empty_notif@example.com")
        self.authenticate(user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 0)
        self.assertEqual(res.data["unread_count"], 0)

    def test_list_notifications_unauthenticated_returns_401(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 401)

    def test_list_notifications_isolation_between_users(self):
        """User A should not see User B's notifications."""
        user_a = self.create_user(email="a@example.com")
        user_b = self.create_user(email="b@example.com")
        self._make_notification(user_b, "B's notification")
        self.authenticate(user_a)
        res = self.client.get(self._url())
        self.assertEqual(res.data["count"], 0)


class MarkNotificationReadTests(AdPortalTestBase):
    """Tests for POST /accounts/read-notification/"""

    def _url(self):
        return reverse("mark_notifications_read")

    def test_mark_specific_notifications_read(self):
        user = self.create_user(email="read@example.com")
        n1 = Notification.objects.create(user=user, message="N1", read=False)
        n2 = Notification.objects.create(user=user, message="N2", read=False)
        self.authenticate(user)
        res = self.client.post(
            self._url(), {"notification_ids": [n1.id]}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        n1.refresh_from_db()
        n2.refresh_from_db()
        self.assertTrue(n1.read)
        self.assertFalse(n2.read)  # N2 should remain unread

    def test_mark_notifications_invalid_body_returns_400(self):
        user = self.create_user(email="read2@example.com")
        self.authenticate(user)
        res = self.client.post(
            self._url(), {"notification_ids": "not-a-list"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_mark_other_users_notifications_are_ignored(self):
        """Should only mark IDs that belong to the authenticated user."""
        user_a = self.create_user(email="ma@example.com")
        user_b = self.create_user(email="mb@example.com")
        n_b = Notification.objects.create(user=user_b, message="B's", read=False)
        self.authenticate(user_a)
        res = self.client.post(
            self._url(), {"notification_ids": [n_b.id]}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        n_b.refresh_from_db()
        self.assertFalse(n_b.read)  # Should NOT be affected


class MarkAllNotificationsReadTests(AdPortalTestBase):
    """Tests for POST /accounts/read-all-notifications/"""

    def _url(self):
        return reverse("mark_all_notifications_read")

    def test_mark_all_read(self):
        user = self.create_user(email="readall@example.com")
        Notification.objects.create(user=user, message="1", read=False)
        Notification.objects.create(user=user, message="2", read=False)
        self.authenticate(user)
        res = self.client.post(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(user=user, read=False).count(), 0
        )


class DeleteNotificationTests(AdPortalTestBase):
    """Tests for POST /accounts/delete-notification/"""

    def _url(self):
        return reverse("delete_notifications")

    def test_delete_specific_notifications(self):
        user = self.create_user(email="del@example.com")
        n1 = Notification.objects.create(user=user, message="To delete")
        n2 = Notification.objects.create(user=user, message="Keep")
        self.authenticate(user)
        res = self.client.post(
            self._url(), {"notification_ids": [n1.id]}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=n1.id).exists())
        self.assertTrue(Notification.objects.filter(id=n2.id).exists())

    def test_delete_notifications_invalid_body_returns_400(self):
        user = self.create_user(email="del2@example.com")
        self.authenticate(user)
        res = self.client.post(
            self._url(), {"notification_ids": "bad"}, format="json"
        )
        self.assertEqual(res.status_code, 400)


class DeleteAllNotificationsTests(AdPortalTestBase):
    """Tests for POST /accounts/delete-all-notifications/"""

    def _url(self):
        return reverse("delete_all_notifications")

    def test_delete_all_notifications(self):
        user = self.create_user(email="delall@example.com")
        Notification.objects.create(user=user, message="1")
        Notification.objects.create(user=user, message="2")
        self.authenticate(user)
        res = self.client.post(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Notification.objects.filter(user=user).count(), 0)


class NotificationSettingsTests(AdPortalTestBase):
    """Tests for GET/PATCH /accounts/notification-settings/"""

    def _url(self):
        return reverse("notification_settings")

    def test_get_settings_auto_creates_if_missing(self):
        user = self.create_user(email="settings@example.com")
        self.authenticate(user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertIn("campaign_performance", res.data)

    def test_patch_settings_success(self):
        user = self.create_user(email="settings2@example.com")
        self.authenticate(user)
        res = self.client.patch(
            self._url(), {"budget_alerts": True}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["budget_alerts"])

    def test_settings_unauthenticated_returns_401(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 401)


class TestNotificationAPITests(AdPortalTestBase):
    """Tests for POST /accounts/test-notifications/"""

    def _url(self):
        return reverse("test_notifications")

    def test_create_test_notification(self):
        user = self.create_user(email="testn@example.com")
        self.authenticate(user)
        res = self.client.post(self._url())
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Notification.objects.filter(user=user).count(), 1)
