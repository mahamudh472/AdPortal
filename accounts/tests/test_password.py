"""
Tests for password management endpoints:
  POST /accounts/resend-otp/
  POST /accounts/password-reset/ (same view as resend-otp)
  POST /accounts/check-otp/
  POST /accounts/password-reset-confirm/
  POST /accounts/change-password/
"""
from unittest.mock import patch

from django.urls import reverse

from accounts.tests.base import AdPortalTestBase


class SendOTPTests(AdPortalTestBase):
    """Tests for POST /accounts/resend-otp/ and POST /accounts/password-reset/"""

    def _url(self):
        return reverse("resend_otp")

    def _reset_url(self):
        return reverse("password_reset")

    @patch("accounts.views.send_otp_email")
    def test_send_otp_success(self, mock_email):
        mock_email.return_value = None
        self.create_user(email="otp@example.com")
        res = self.client.post(self._url(), {"email": "otp@example.com"}, format="json")
        self.assertEqual(res.status_code, 200)

    @patch("accounts.views.send_otp_email", side_effect=Exception("SMTP down"))
    def test_send_otp_email_failure_still_returns_200(self, mock_email):
        self.create_user(email="otpfail@example.com")
        res = self.client.post(
            self._url(), {"email": "otpfail@example.com"}, format="json"
        )
        self.assertEqual(res.status_code, 200)

    def test_send_otp_unknown_email_returns_400(self):
        res = self.client.post(
            self._url(), {"email": "ghost@example.com"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    @patch("accounts.views.send_otp_email")
    def test_password_reset_endpoint_same_behaviour(self, mock_email):
        """password-reset is the same view — just verify it works via that URL too."""
        mock_email.return_value = None
        self.create_user(email="pwr@example.com")
        res = self.client.post(
            self._reset_url(), {"email": "pwr@example.com"}, format="json"
        )
        self.assertEqual(res.status_code, 200)


class CheckOTPTests(AdPortalTestBase):
    """Tests for POST /accounts/check-otp/"""

    def _url(self):
        return reverse("password_reset_verify")

    def test_check_otp_valid_returns_200(self):
        user = self.create_user(email="checkotp@example.com")
        self.create_otp(user, code="777777")
        res = self.client.post(
            self._url(),
            {"email": "checkotp@example.com", "otp": "777777"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)

    def test_check_otp_expired_returns_400(self):
        user = self.create_user(email="expiredotp@example.com")
        self.create_otp(user, code="888888", expired=True)
        res = self.client.post(
            self._url(),
            {"email": "expiredotp@example.com", "otp": "888888"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_check_otp_used_returns_400(self):
        user = self.create_user(email="usedotp@example.com")
        self.create_otp(user, code="999999", used=True)
        res = self.client.post(
            self._url(),
            {"email": "usedotp@example.com", "otp": "999999"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_check_otp_wrong_code_returns_400(self):
        user = self.create_user(email="wrongotp@example.com")
        self.create_otp(user, code="111111")
        res = self.client.post(
            self._url(),
            {"email": "wrongotp@example.com", "otp": "000000"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_check_otp_unknown_user_returns_404(self):
        res = self.client.post(
            self._url(),
            {"email": "nobody@example.com", "otp": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, 404)

    def test_check_otp_missing_fields_returns_400(self):
        res = self.client.post(self._url(), {"email": "x@x.com"}, format="json")
        self.assertEqual(res.status_code, 400)


class PasswordResetConfirmTests(AdPortalTestBase):
    """Tests for POST /accounts/password-reset-confirm/"""

    def _url(self):
        return reverse("password_reset_confirm")

    def test_reset_password_success(self):
        user = self.create_user(email="reset@example.com", password="OldPass123!")
        self.create_otp(user, code="555555")
        res = self.client.post(
            self._url(),
            {
                "email": "reset@example.com",
                "otp": "555555",
                "new_password": "NewPass456!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPass456!"))

    def test_reset_password_invalid_otp_returns_400(self):
        user = self.create_user(email="reset2@example.com")
        self.create_otp(user, code="444444")
        res = self.client.post(
            self._url(),
            {
                "email": "reset2@example.com",
                "otp": "000000",
                "new_password": "NewPass456!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_reset_password_expired_otp_returns_400(self):
        user = self.create_user(email="reset3@example.com")
        self.create_otp(user, code="333333", expired=True)
        res = self.client.post(
            self._url(),
            {
                "email": "reset3@example.com",
                "otp": "333333",
                "new_password": "NewPass456!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_reset_password_unknown_user_returns_404(self):
        res = self.client.post(
            self._url(),
            {
                "email": "nobody@example.com",
                "otp": "123456",
                "new_password": "Whatever1!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 404)

    def test_reset_password_missing_new_password_returns_400(self):
        user = self.create_user(email="reset4@example.com")
        self.create_otp(user, code="111111")
        res = self.client.post(
            self._url(),
            {"email": "reset4@example.com", "otp": "111111"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_reset_password_otp_cannot_be_reused(self):
        """Using the same OTP a second time should fail."""
        user = self.create_user(email="reset5@example.com")
        self.create_otp(user, code="222222")
        payload = {
            "email": "reset5@example.com",
            "otp": "222222",
            "new_password": "NewPass456!",
        }
        self.client.post(self._url(), payload, format="json")
        # Second attempt with same OTP
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)


class ChangePasswordTests(AdPortalTestBase):
    """Tests for POST /accounts/change-password/"""

    def _url(self):
        return reverse("change_password")

    def test_change_password_success(self):
        user = self.create_user(email="chpwd@example.com", password="OldPass123!")
        self.authenticate(user)
        res = self.client.post(
            self._url(),
            {
                "old_password": "OldPass123!",
                "new_password": "NewPass456!",
                "confirm_password": "NewPass456!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPass456!"))

    def test_change_password_wrong_old_password_returns_400(self):
        user = self.create_user(email="chpwd2@example.com", password="OldPass123!")
        self.authenticate(user)
        res = self.client.post(
            self._url(),
            {
                "old_password": "WrongPass!",
                "new_password": "NewPass456!",
                "confirm_password": "NewPass456!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_change_password_mismatched_new_passwords_returns_400(self):
        user = self.create_user(email="chpwd3@example.com", password="OldPass123!")
        self.authenticate(user)
        res = self.client.post(
            self._url(),
            {
                "old_password": "OldPass123!",
                "new_password": "NewPass456!",
                "confirm_password": "DifferentPass!",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)
