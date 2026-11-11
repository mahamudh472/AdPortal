"""
Tests for authentication endpoints:
  POST /accounts/register/
  POST /accounts/verify-email/
  POST /accounts/login/
  POST /accounts/token/refresh/
  POST /accounts/logout/
"""
from unittest.mock import patch

from django.urls import reverse

from apps.accounts.models import User, OTP
from apps.accounts.tests.base import AdPortalTestBase


class RegisterTests(AdPortalTestBase):

    def _url(self):
        return reverse("register")

    def _valid_payload(self, email="newuser@example.com"):
        return {
            "full_name": "New User",
            "email": email,
            "password": "SecurePass123!",
            "timezone": "UTC",
        }

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("apps.accounts.email_utils.send_otp_email")
    def test_register_success(self, mock_email):
        """Valid data creates an inactive user and sends OTP."""
        mock_email.return_value = None
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        user = User.objects.get(email="newuser@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(OTP.objects.filter(user=user).exists())

    @patch("apps.accounts.email_utils.send_otp_email", side_effect=Exception("SMTP down"))
    def test_register_email_failure_still_returns_201(self, mock_email):
        """Email failure should not block registration."""
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 201)

    # ── Duplicate / inactive user re-registration ───────────────────────────

    @patch("apps.accounts.email_utils.send_otp_email")
    def test_register_overwrites_inactive_duplicate(self, mock_email):
        """Registering with same email of inactive user deletes old record first."""
        mock_email.return_value = None
        # First registration
        self.client.post(self._url(), self._valid_payload(), format="json")
        # Second registration with same email
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(User.objects.filter(email="newuser@example.com").count(), 1)

    # ── Edge / error cases ──────────────────────────────────────────────────

    def test_register_missing_email_returns_400(self):
        payload = self._valid_payload()
        payload.pop("email")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_register_missing_timezone_returns_400(self):
        payload = self._valid_payload()
        payload.pop("timezone")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_register_duplicate_active_user_returns_400(self):
        """Active user cannot register again with the same email."""
        self.create_user(email="existing@example.com")
        payload = self._valid_payload(email="existing@example.com")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)


class VerifyEmailTests(AdPortalTestBase):

    def _url(self):
        return reverse("verify_email")

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("apps.accounts.views.send_welcome_email")
    def test_verify_email_success(self, mock_welcome):
        """Valid OTP activates user."""
        mock_welcome.return_value = None
        user = self.create_user(email="verify@example.com", active=False)
        otp = self.create_otp(user, code="654321")
        res = self.client.post(
            self._url(),
            {"email": "verify@example.com", "otp": "654321"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        otp.refresh_from_db()
        self.assertTrue(otp.is_used)

    # ── Error cases ─────────────────────────────────────────────────────────

    def test_verify_email_wrong_otp_returns_400(self):
        user = self.create_user(email="v2@example.com", active=False)
        self.create_otp(user, code="111111")
        res = self.client.post(
            self._url(),
            {"email": "v2@example.com", "otp": "999999"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_verify_email_expired_otp_returns_400(self):
        user = self.create_user(email="v3@example.com", active=False)
        self.create_otp(user, code="222222", expired=True)
        res = self.client.post(
            self._url(),
            {"email": "v3@example.com", "otp": "222222"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_verify_email_unknown_email_returns_400(self):
        res = self.client.post(
            self._url(),
            {"email": "ghost@example.com", "otp": "000000"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_verify_email_missing_fields_returns_400(self):
        res = self.client.post(self._url(), {"email": "x@x.com"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_verify_already_used_otp_returns_400(self):
        user = self.create_user(email="v4@example.com", active=False)
        self.create_otp(user, code="333333", used=True)
        res = self.client.post(
            self._url(),
            {"email": "v4@example.com", "otp": "333333"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)


class LoginTests(AdPortalTestBase):

    def _url(self):
        return reverse("login")

    # ── Happy path ──────────────────────────────────────────────────────────

    def test_login_success_returns_tokens(self):
        self.create_user(email="login@example.com", password="Pass123!")
        res = self.client.post(
            self._url(),
            {"email": "login@example.com", "password": "Pass123!"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertIn("user", res.data)

    # ── Error cases ─────────────────────────────────────────────────────────

    def test_login_wrong_password_returns_401(self):
        self.create_user(email="login2@example.com", password="RightPass!")
        res = self.client.post(
            self._url(),
            {"email": "login2@example.com", "password": "WrongPass!"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_login_inactive_user_returns_400(self):
        self.create_user(email="inactive@example.com", password="Pass123!", active=False)
        res = self.client.post(
            self._url(),
            {"email": "inactive@example.com", "password": "Pass123!"},
            format="json",
        )
        self.assertIn(res.status_code, [400, 401])

    def test_login_unknown_email_returns_401(self):
        res = self.client.post(
            self._url(),
            {"email": "nobody@example.com", "password": "Anything1!"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_login_success_returns_absolute_avatar_url(self):
        user = self.create_user(email="login_avatar@example.com", password="Pass123!")
        from django.core.files.uploadedfile import SimpleUploadedFile
        user.avatar = SimpleUploadedFile(
            name='test_avatar.jpg',
            content=b'dummy_image_data',
            content_type='image/jpeg'
        )
        user.save()

        res = self.client.post(
            self._url(),
            {"email": "login_avatar@example.com", "password": "Pass123!"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("user", res.data)
        avatar_url = res.data["user"]["avatar"]
        self.assertIsNotNone(avatar_url)
        self.assertTrue(avatar_url.startswith("http://") or avatar_url.startswith("https://"))
        self.assertIn("/media/avatars/", avatar_url)


class TokenRefreshTests(AdPortalTestBase):

    def _url(self):
        return reverse("token_refresh")

    def test_token_refresh_success(self):
        user = self.create_user(email="refresh@example.com")
        _, refresh = self.get_tokens_for_user(user)
        res = self.client.post(self._url(), {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)

    def test_token_refresh_invalid_token_returns_401(self):
        res = self.client.post(
            self._url(), {"refresh": "notavalidtoken"}, format="json"
        )
        self.assertEqual(res.status_code, 401)


class LogoutTests(AdPortalTestBase):

    def _url(self):
        return reverse("logout")

    def test_logout_success_blacklists_token(self):
        user = self.create_user(email="logout@example.com")
        _, refresh = self.get_tokens_for_user(user)
        self.authenticate(user)
        res = self.client.post(
            self._url(), {"refresh_token": refresh}, format="json"
        )
        self.assertEqual(res.status_code, 205)

    def test_logout_without_refresh_token_returns_400(self):
        user = self.create_user(email="logout2@example.com")
        self.authenticate(user)
        res = self.client.post(self._url(), {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_logout_unauthenticated_returns_401(self):
        res = self.client.post(self._url(), {"refresh_token": "x"}, format="json")
        self.assertEqual(res.status_code, 401)
