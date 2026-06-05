"""
Tests for AI-powered endpoints:
  POST /api/v1/main/generate-ai-copy/?org_id=
  POST /api/v1/main/generate-ad-copy/?org_id=
  GET  /api/v1/main/ai-insights/?org_id=
"""
from unittest.mock import patch

from apps.main.models import AIInsight
from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"
MOCK_COPY_RESPONSE = ["Headline 1", "Headline 2"]


class AICopyGeneratorTests(MainTestBase):
    """Tests for POST /api/v1/main/generate-ai-copy/"""

    def _url(self):
        return f"{BASE}/generate-ai-copy/?org_id={self.org_id}"

    def _valid_payload(self):
        return {
            "product": "Running Shoes",
            "audience": "Fitness enthusiasts",
            "benefits": "Lightweight, durable, comfortable",
            "tone": "Friendly",
            "copy_type": "Headlines",
        }

    @patch("apps.main.services.ai.generate_copy", return_value=MOCK_COPY_RESPONSE)
    def test_generate_ai_copy_success(self, mock_gen):
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("generated_copies", res.data)
        mock_gen.assert_called_once()

    @patch("apps.main.services.ai.generate_copy", return_value=MOCK_COPY_RESPONSE)
    def test_generate_ai_copy_missing_fields_returns_400(self, mock_gen):
        res = self.client.post(self._url(), {"product": "Shoes"}, format="json")
        self.assertEqual(res.status_code, 400)
        mock_gen.assert_not_called()

    @patch("apps.main.services.ai.generate_copy", return_value=MOCK_COPY_RESPONSE)
    def test_generate_ai_copy_non_member_returns_403(self, mock_gen):
        other = self.create_user(email="ai_stranger@example.com")
        self.authenticate(other)
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 403)

    def test_generate_ai_copy_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 401)


class AIAdCopyGeneratorTests(MainTestBase):
    """Tests for POST /api/v1/main/generate-ad-copy/"""

    def _url(self):
        return f"{BASE}/generate-ad-copy/?org_id={self.org_id}"

    def _valid_payload(self):
        return {
            "product_service": "Cloud Storage",
            "target_audience": "Small businesses",
            "key_benefits": "Cheap, fast, secure",
            "tone": "professional",
        }

    @patch("apps.main.services.ai.generate_ad_copy", return_value={"headline": "Test"})
    def test_generate_ad_copy_success(self, mock_gen):
        res = self.client.post(self._url(), self._valid_payload(), format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Ad copy", res.data)

    @patch("apps.main.services.ai.generate_ad_copy", return_value={"headline": "Test"})
    def test_generate_ad_copy_missing_fields_returns_400(self, mock_gen):
        res = self.client.post(self._url(), {"product_service": "Cloud"}, format="json")
        self.assertEqual(res.status_code, 400)


class AIInsightListTests(MainTestBase):
    """Tests for GET /api/v1/main/ai-insights/"""

    def _url(self):
        return f"{BASE}/ai-insights/"

    def test_get_ai_insights_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)

    def test_get_ai_insights_lists_org_insights(self):
        campaign = self.create_campaign("Insight Campaign")
        AIInsight.objects.create(
            organization=self.org,
            campaign=campaign,
            title="Test Insight",
            description="Some insight",
            impact="HIGH",
        )
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data["count"], 1)

    def test_get_ai_insights_non_member_returns_403(self):
        other = self.create_user(email="ai_insight_stranger@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)
