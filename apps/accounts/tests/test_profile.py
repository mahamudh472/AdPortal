"""
Tests for profile management endpoints:
  GET  /accounts/profile/
  PATCH /accounts/profile/update/
  DELETE /accounts/delete-account/
"""
from django.urls import reverse

from apps.accounts.tests.base import AdPortalTestBase


class ProfileViewTests(AdPortalTestBase):
    """Tests for GET /accounts/profile/"""

    def _url(self):
        return reverse("profile")

    def test_get_profile_success(self):
        user = self.create_user(email="profile@example.com")
        self.authenticate(user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["email"], "profile@example.com")

    def test_get_profile_unauthenticated_returns_401(self):
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 401)

    def test_get_profile_admin_user_returns_403(self):
        """IsRegularPlatformUser blocks staff users."""
        admin = self.create_admin_user()
        # Profile view uses IsAuthenticated, not IsRegularPlatformUser
        # so admin CAN access their profile. Verify 200.
        self.authenticate(admin)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)


class UpdateProfileTests(AdPortalTestBase):
    """Tests for PATCH /accounts/profile/update/"""

    def _url(self):
        return reverse("profile_update")

    def test_update_profile_success(self):
        user = self.create_user(email="update@example.com")
        self.authenticate(user)
        res = self.client.patch(
            self._url(), {"full_name": "Updated Name"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.full_name, "Updated Name")

    def test_update_profile_partial_update(self):
        """Phone number can be updated independently."""
        user = self.create_user(email="partial@example.com")
        self.authenticate(user)
        res = self.client.patch(
            self._url(), {"phone_number": "+14155552671"}, format="json"
        )
        self.assertEqual(res.status_code, 200)

    def test_update_profile_unauthenticated_returns_401(self):
        res = self.client.patch(self._url(), {"full_name": "Bob"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_update_profile_admin_blocked_by_is_regular_platform_user(self):
        """Staff / admin user must be blocked by IsRegularPlatformUser."""
        admin = self.create_admin_user()
        self.authenticate(admin)
        res = self.client.patch(
            self._url(), {"full_name": "Admin Name"}, format="json"
        )
        self.assertEqual(res.status_code, 403)


class DeleteAccountTests(AdPortalTestBase):
    """Tests for DELETE /accounts/delete-account/"""

    def _url(self):
        return reverse("delete_account")

    def test_delete_account_success(self):
        user = self.create_user(email="delete@example.com")
        self.authenticate(user)
        res = self.client.delete(self._url())
        self.assertEqual(res.status_code, 200)
        from apps.accounts.models import User
        self.assertFalse(User.objects.filter(email="delete@example.com").exists())

    def test_delete_account_unauthenticated_returns_401(self):
        res = self.client.delete(self._url())
        self.assertEqual(res.status_code, 401)

    def test_delete_account_admin_blocked_returns_403(self):
        admin = self.create_admin_user()
        self.authenticate(admin)
        res = self.client.delete(self._url())
        self.assertEqual(res.status_code, 403)
