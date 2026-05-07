"""
Regression tests for the TikTok test publish flow.
"""
from types import SimpleNamespace
from unittest.mock import patch

from main.models import AdGroup, CampaignBudget, PlatformCampaign
from main.tests.base import MainTestBase


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class TikTokCreateAdEndpointTests(MainTestBase):

    def _url(self):
        return f"/api/v1/main/test/create-ad-on-platform/?org_id={self.org_id}"

    def _setup_tiktok_stack(self, campaign_name="Existing TikTok Campaign"):
        integration = self.create_integration("TIKTOK")
        campaign = self.create_campaign(campaign_name)
        CampaignBudget.objects.create(
            campaign=campaign,
            platform="TIKTOK",
            budget_type="DAILY",
            daily_budget_minor=5000,
            start_date="2026-05-07",
            end_date=None,
            run_continuously=True,
        )
        platform_campaign = PlatformCampaign.objects.create(
            unified_campaign=campaign,
            integration=integration,
        )
        AdGroup.objects.create(
            platform_campaign=platform_campaign,
            name="TikTok Ad Group",
            targeting_config={},
        )
        return campaign, integration, platform_campaign

    @patch("main.utils.tiktok_handler.create_tiktok_ad_creative")
    @patch("main.utils.tiktok_handler.requests.post")
    def test_duplicate_campaign_name_retries_and_still_creates_ad(
        self,
        mock_post,
        mock_create_creative,
    ):
        campaign, _, platform_campaign = self._setup_tiktok_stack()

        mock_post.side_effect = [
            _FakeResponse(
                400,
                {
                    "code": 10001,
                    "message": "campaign name already exists",
                },
            ),
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {"campaign_id": "camp-123"},
                },
            ),
            _FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {"adgroup_id": "adgroup-123"},
                },
            ),
        ]
        mock_create_creative.return_value = SimpleNamespace(
            id=456,
            platform_ad_id="ad-456",
        )

        res = self.client.post(
            self._url(),
            {
                "platform": "TIKTOK",
                "campaign_id": campaign.pk,
            },
            format="json",
        )

        response_data = getattr(res, "data", {})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(response_data["platform_campaign_id"], "camp-123")
        self.assertEqual(response_data["platform_adgroup_id"], "adgroup-123")
        self.assertEqual(response_data["platform_ad_id"], "ad-456")
        self.assertEqual(mock_post.call_count, 3)
        adgroup_payload = mock_post.call_args_list[2].kwargs["json"]
        self.assertIn("schedule_start_time", adgroup_payload)
        self.assertEqual(adgroup_payload["schedule_type"], "SCHEDULE_FROM_NOW")
        platform_campaign.refresh_from_db()
        self.assertEqual(platform_campaign.platform_campaign_id, "camp-123")

    @patch("main.views.create_full_ad_for_tiktok")
    def test_reuses_existing_tiktok_campaign_on_retry(self, mock_create_full_ad):
        campaign, _, platform_campaign = self._setup_tiktok_stack()
        platform_campaign.platform_campaign_id = "camp-existing"
        platform_campaign.save(update_fields=["platform_campaign_id"])

        mock_create_full_ad.return_value = {
            "campaign_id": "camp-existing",
            "adgroup_id": "adgroup-existing",
            "ad_id": 456,
            "platform_ad_id": "ad-456",
        }

        res = self.client.post(
            self._url(),
            {
                "platform": "TIKTOK",
                "campaign_id": campaign.pk,
            },
            format="json",
        )

        self.assertEqual(res.status_code, 201)
        _, kwargs = mock_create_full_ad.call_args
        self.assertFalse(kwargs["force_recreate_campaign"])
