"""
Tests for the ad creation/update endpoints:
  POST /api/v1/main/create-ad/?org_id=    (create draft or publish)
"""
from unittest.mock import patch

from apps.main.models import UnifiedCampaign
from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"
EXPECTED_CAMPAIGN_FIELDS = {
    "id",
    "name",
    "objective",
    "platforms",
    "matrics",
    "ads",
    "audience_targeting",
    "status",
    "created_at",
    "ai_insights",
    "total_budget",
    "total_spent",
    "remaining_budget",
    "budgets",
    "file_url",
}


class CreateAdDraftTests(MainTestBase):
    """POST /api/v1/main/create-ad/ with draft=true"""

    def setUp(self):
        super().setUp()
        self.create_integration("META")

    def _url(self):
        return f"{BASE}/create-ad/?org_id={self.org_id}"

    def _draft_payload(self, name="My Campaign"):
        return {
            "campaign_name": name,
            "objective": "TRAFFIC",
            "draft": True,
            "platforms": ["META"],
        }

    def test_create_draft_campaign_returns_201(self):
        res = self.client.post(self._url(), self._draft_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(
            UnifiedCampaign.objects.filter(name="My Campaign", status="DRAFT").exists()
        )

    def test_create_draft_response_matches_campaign_retrieve_shape(self):
        res = self.client.post(self._url(), self._draft_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(EXPECTED_CAMPAIGN_FIELDS.issubset(set(res.data.keys())))

    def test_create_draft_without_campaign_name_returns_400(self):
        payload = self._draft_payload()
        payload.pop("campaign_name")
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)

    def test_create_draft_duplicate_name_returns_400(self):
        """Two campaigns with the same name in the same org should fail."""
        self.create_campaign("Duplicate Name")
        res = self.client.post(self._url(), self._draft_payload("Duplicate Name"), format="json")
        self.assertEqual(res.status_code, 400)

    def test_create_draft_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.post(self._url(), self._draft_payload(), format="json")
        self.assertEqual(res.status_code, 401)

    def test_create_draft_invalid_org_returns_400(self):
        res = self.client.post(
            f"{BASE}/create-ad/?org_id=bad_org", self._draft_payload(), format="json"
        )
        self.assertIn(res.status_code, [400, 403])


class UpdateAdDraftTests(MainTestBase):
    """POST /api/v1/main/create-ad/ with campaign_id — update an existing draft."""

    def _url(self):
        return f"{BASE}/create-ad/?org_id={self.org_id}"

    def test_update_draft_merges_data_returns_200(self):
        campaign = self.create_campaign("Updatable Campaign")
        res = self.client.post(
            self._url(),
            {"campaign_id": campaign.id, "objective": "AWARENESS", "draft": True},
            format="json",
        )
        self.assertEqual(res.status_code, 200)

    def test_update_nonexistent_campaign_id_returns_400(self):
        res = self.client.post(
            self._url(),
            {"campaign_id": 99999, "objective": "TRAFFIC", "draft": True},
            format="json",
        )
        self.assertEqual(res.status_code, 400)


class PublishAdTests(MainTestBase):
    """POST /api/v1/main/create-ad/ with draft=false — full publish flow."""

    def setUp(self):
        super().setUp()
        self.create_integration("META")

    def _url(self):
        return f"{BASE}/create-ad/?org_id={self.org_id}"

    def _full_payload(self, name="Publishable Campaign"):
        return {
            "campaign_name": name,
            "objective": "TRAFFIC",
            "draft": False,
            "platforms": ["META"],
            "budgets": [
                {
                    "platform": "META",
                    "budget_type": "DAILY",
                    "budget": 5000,
                    "start_date": "2026-04-01",
                    "end_date": None,
                    "run_continuously": True,
                }
            ],
            "min_age": 18,
            "max_age": 45,
            "gender": "all",
            "locations": ["US"],
            "keywords": ["shoes"],
            "ad_name": "My Ad",
            "headline": "Great Shoes",
            "primary_text": "Buy now",
            "description": "Limited offer",
            "call_to_action": "SHOP_NOW",
            "destination_url": "https://example.com",
        }

    @patch("apps.main.services.ad_creation.create_full_ad_for_platform")
    def test_publish_campaign_with_all_fields_returns_201(self, mock_create):
        mock_create.return_value = None
        res = self.client.post(self._url(), self._full_payload(), format="json")
        self.assertIn(res.status_code, [200, 201])

    @patch("apps.main.services.ad_creation.create_full_ad_for_platform")
    def test_publish_campaign_missing_required_fields_returns_400(self, mock_create):
        """Publishing without all required fields should fail before calling the platform."""
        payload = {
            "campaign_name": "Incomplete Camp",
            "objective": "TRAFFIC",
            "draft": False,
            "platforms": ["META"],
            # missing budgets, targeting, creative
        }
        res = self.client.post(self._url(), payload, format="json")
        self.assertEqual(res.status_code, 400)
        mock_create.assert_not_called()

    @patch("apps.main.services.ad_creation.create_full_ad_for_platform")
    def test_publish_without_optional_fields_defaults_ad_name(self, mock_create):
        """Ad name, description and keywords are optional in the wizard."""
        mock_create.return_value = None
        payload = self._full_payload("No Optionals")
        for field in ("ad_name", "description", "keywords"):
            payload.pop(field)
        res = self.client.post(self._url(), payload, format="json")
        self.assertIn(res.status_code, [200, 201])
        self.assertEqual(mock_create.call_args.args[1]["ad_name"], "No Optionals - Default Ad")


class CreativeDraftFieldsTests(MainTestBase):
    def setUp(self):
        super().setUp()
        self.create_integration("META")

    def test_draft_keeps_ad_format_and_creative_keywords_and_allows_clearing(self):
        url = f"{BASE}/create-ad/?org_id={self.org_id}"
        created = self.client.post(url, {"campaign_name": "Creative Draft", "draft": True}, format="json")
        campaign_id = created.data["id"]

        res = self.client.post(url, {
            "campaign_id": campaign_id, "ad_format": "video", "creative_keywords": "sound, music",
            "headline": "Hi", "description": "Temp",
        }, format="json")
        self.assertEqual(res.status_code, 200)
        ad = res.data["ads"][0]
        self.assertEqual(ad["ad_format"], "video")
        self.assertEqual(ad["creative_keywords"], "sound, music")

        cleared = self.client.post(url, {"campaign_id": campaign_id, "description": ""}, format="json")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.data["ads"][0]["description"], "")

    def test_invalid_ad_format_is_rejected(self):
        url = f"{BASE}/create-ad/?org_id={self.org_id}"
        res = self.client.post(url, {"campaign_name": "Bad Format", "ad_format": "gif"}, format="json")
        self.assertEqual(res.status_code, 400)
