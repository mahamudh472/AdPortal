"""
Tests for the campaign wizard guidance endpoints:
  GET  /api/v1/main/campaign-wizard/config/
  POST /api/v1/main/campaign-wizard/name-suggestions/
  POST /api/v1/main/campaign-wizard/budget-recommendation/
  POST /api/v1/main/campaign-wizard/creative-score/
  POST /api/v1/main/audience-reach-estimate/
"""
from apps.main.models import UnifiedCampaign
from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"


class CampaignWizardTests(MainTestBase):
    def _url(self, path):
        return f"{BASE}/{path}/?org_id={self.org_id}"

    def test_config_marks_connected_platforms(self):
        self.create_integration("GOOGLE")
        res = self.client.get(self._url("campaign-wizard/config"))
        self.assertEqual(res.status_code, 200)
        by_key = {p["key"]: p for p in res.data["platforms"]}
        self.assertTrue(by_key["GOOGLE"]["connected"])
        self.assertFalse(by_key["META"]["connected"])
        self.assertEqual(len(res.data["objectives"]), 6)
        self.assertEqual(sum(o["recommended"] for o in res.data["objectives"]), 1)

    def test_config_requires_org(self):
        res = self.client.get(f"{BASE}/campaign-wizard/config/")
        self.assertIn(res.status_code, (400, 403))

    def test_config_unknown_campaign_is_400(self):
        res = self.client.get(self._url("campaign-wizard/config") + "&campaign_id=999999")
        self.assertEqual(res.status_code, 400)

    def test_name_suggestions_rotate_and_skip_taken_names(self):
        res = self.client.post(self._url("campaign-wizard/name-suggestions"), {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["suggestions"]), 3)
        more = self.client.post(
            self._url("campaign-wizard/name-suggestions"),
            {"offset": res.data["next_offset"]}, format="json",
        )
        self.assertNotEqual(res.data["suggestions"], more.data["suggestions"])

        UnifiedCampaign.objects.create(organization=self.org, name=res.data["suggestions"][0])
        again = self.client.post(self._url("campaign-wizard/name-suggestions"), {}, format="json")
        self.assertNotIn(res.data["suggestions"][0], again.data["suggestions"])

    def test_budget_split_sums_to_total(self):
        res = self.client.post(
            self._url("campaign-wizard/budget-recommendation"),
            {"platforms": ["META", "GOOGLE", "TIKTOK"], "objective": "CONVERSIONS", "daily_budget": 101, "days": 10},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sum(s["daily_budget"] for s in res.data["split"]), 101)
        self.assertEqual(res.data["total_spend"], 1010)
        self.assertEqual(res.data["recommended_daily_budget"], 100)

    def test_budget_rejects_unknown_platform(self):
        res = self.client.post(
            self._url("campaign-wizard/budget-recommendation"), {"platforms": ["MYSPACE"]}, format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_creative_score(self):
        empty = self.client.post(self._url("campaign-wizard/creative-score"), {}, format="json")
        self.assertEqual(empty.data["score"], 0)
        full = self.client.post(self._url("campaign-wizard/creative-score"), {
            "headline": "Premium Sound. Everyday.",
            "primary_text": "High quality. Affordable price. Shop now and upgrade.",
            "description": "Great sound", "call_to_action": "Shop now",
            "destination_url": "https://example.com", "keywords": "headphones", "has_asset": True,
        }, format="json")
        self.assertEqual(full.data["score"], 100)
        self.assertTrue(all(c["ok"] for c in full.data["checks"]))

    def test_audience_reach_includes_insights(self):
        res = self.client.post(self._url("audience-reach-estimate"), {"keywords": "tech, fitness"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn(res.data["level"], {"optimal", "too_specific", "too_broad"})
        self.assertEqual(len(res.data["insights"]), 4)
        self.assertNotIn("Tech", res.data["interest_suggestions"])
