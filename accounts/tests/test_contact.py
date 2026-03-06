"""
Tests for the contact-us endpoint:
  POST /accounts/contact-us/
"""
from django.urls import reverse

from accounts.models import ContactUsMessage
from accounts.tests.base import AdPortalTestBase


class ContactUsTests(AdPortalTestBase):
    """Tests for POST /accounts/contact-us/"""

    def _url(self):
        return reverse("contact_us")

    def _valid_payload(self):
        return {
            "name": "Alice",
            "email": "alice@example.com",
            "subject": "Question about billing",
            "message": "I have a question about my invoice.",
        }

    def test_contact_us_success_creates_message(self):
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(ContactUsMessage.objects.count(), 1)
        msg = ContactUsMessage.objects.first()
        self.assertEqual(msg.email, "alice@example.com")

    def test_contact_us_missing_name_returns_400(self):
        payload = self._valid_payload()
        payload.pop("name")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_contact_us_missing_email_returns_400(self):
        payload = self._valid_payload()
        payload.pop("email")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_contact_us_missing_message_returns_400(self):
        payload = self._valid_payload()
        payload.pop("message")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_contact_us_invalid_email_returns_400(self):
        payload = self._valid_payload()
        payload["email"] = "not-an-email"
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_contact_us_no_auth_required(self):
        """Endpoint must be accessible without a token."""
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertNotEqual(res.status_code, 401)
        self.assertNotEqual(res.status_code, 403)
