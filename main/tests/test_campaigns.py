"""
Tests for campaign CRUD endpoints:
  GET  /api/v1/main/campaigns/?org_id=
  GET  /api/v1/main/campaign/<id>/?org_id=
  PUT/PATCH /api/v1/main/campaign/<id>/?org_id=
  DELETE /api/v1/main/campaign/<id>/?org_id=
  POST /api/v1/main/campaign/<id>/toggle-status/?org_id=
"""
from main.models import UnifiedCampaign
from main.tests.base import MainTestBase


BASE = "/api/v1/main"


class CampaignListTests(MainTestBase):
    """Tests for GET /api/v1/main/campaigns/"""

    def _url(self):
        return f"{BASE}/campaigns/"

    def test_list_campaigns_returns_200(self):
        self.create_campaign("Campaign Alpha")
        self.create_campaign("Campaign Beta")
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data["count"], 2)

    def test_list_campaigns_search_by_name(self):
        self.create_campaign("Unique Name Campaign")
        self.create_campaign("Other Campaign")
        res = self.client.get(self._url(), {"org_id": self.org_id, "search": "Unique"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)

    def test_list_campaigns_filter_by_status(self):
        self.create_campaign("Draft One", status="DRAFT")
        self.create_campaign("Active One", status="ACTIVE")
        res = self.client.get(self._url(), {"org_id": self.org_id, "status": "DRAFT"})
        self.assertEqual(res.status_code, 200)
        for item in res.data["results"]:
            self.assertEqual(item["status"], "DRAFT")

    def test_list_campaigns_non_member_returns_403(self):
        other = self.create_user(email="stranger_camp@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)

    def test_list_campaigns_invalid_org_returns_400_or_403(self):
        res = self.client.get(self._url(), {"org_id": "bad_org"})
        self.assertIn(res.status_code, [400, 403])


class CampaignRetrieveUpdateDeleteTests(MainTestBase):
    """Tests for GET/PUT/PATCH/DELETE /api/v1/main/campaign/<id>/"""

    def _url(self, campaign_id):
        return f"{BASE}/campaign/{campaign_id}/?org_id={self.org_id}"

    def test_retrieve_campaign_success(self):
        campaign = self.create_campaign("Retrieve Me")
        res = self.client.get(self._url(campaign.id))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], "Retrieve Me")

    def test_retrieve_campaign_wrong_org_returns_404(self):
        """Campaign from another org must not be accessible."""
        other_owner = self.create_user(email="owner2@example.com")
        other_org = self.create_organization(other_owner, name="Other Org")
        other_campaign = UnifiedCampaign.objects.create(
            organization=other_org, name="Other Org Campaign", status="DRAFT"
        )
        res = self.client.get(self._url(other_campaign.id))
        self.assertEqual(res.status_code, 404)

    def test_update_campaign_name_success(self):
        campaign = self.create_campaign("Old Name")
        res = self.client.patch(self._url(campaign.id), {"name": "New Name"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_delete_campaign_as_owner_success(self):
        campaign = self.create_campaign("Delete Me")
        res = self.client.delete(self._url(campaign.id))
        self.assertEqual(res.status_code, 204)
        self.assertFalse(UnifiedCampaign.objects.filter(id=campaign.id).exists())

    def test_delete_campaign_as_member_returns_403(self):
        """MEMBER role cannot delete campaigns."""
        member = self.create_user(email="member_del@example.com")
        self.add_member(member, self.org, role="MEMBER")
        campaign = self.create_campaign("Cant Delete Me")
        self.authenticate(member)
        res = self.client.delete(self._url(campaign.id))
        self.assertEqual(res.status_code, 403)


class CampaignToggleStatusTests(MainTestBase):
    """Tests for POST /api/v1/main/campaign/<id>/toggle-status/"""

    def _url(self, campaign_id):
        return f"{BASE}/campaign/{campaign_id}/toggle-status/?org_id={self.org_id}"

    def test_toggle_active_to_paused(self):
        campaign = self.create_campaign("Active Camp", status="ACTIVE")
        res = self.client.post(self._url(campaign.id), {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "PAUSED")

    def test_toggle_paused_to_active(self):
        campaign = self.create_campaign("Paused Camp", status="PAUSED")
        res = self.client.post(self._url(campaign.id), {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "ACTIVE")

    def test_toggle_draft_campaign_returns_400(self):
        campaign = self.create_campaign("Draft Camp", status="DRAFT")
        res = self.client.post(self._url(campaign.id), {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_toggle_archived_campaign_returns_400(self):
        campaign = self.create_campaign("Archived Camp", status="ARCHIVED")
        res = self.client.post(self._url(campaign.id), {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_toggle_nonexistent_campaign_returns_400(self):
        res = self.client.post(f"{BASE}/campaign/999999/toggle-status/?org_id={self.org_id}", {}, format="json")
        self.assertIn(res.status_code, [400, 404])
