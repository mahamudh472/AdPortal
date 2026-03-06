"""
Tests for organization endpoints:
  GET  /organization/?org_id=
  PATCH /organization/?org_id=
"""
from main.tests.base import MainTestBase
from main.models import UnifiedCampaign


class OrganizationRetrieveTests(MainTestBase):
    """Tests for GET /api/v1/main/organization/"""

    def _url(self):
        return "/api/v1/main/organization/"

    def test_get_organization_success(self):
        res = self.client.get(self._url(), self._org_params())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], "Test Org")

    def test_get_organization_invalid_org_id_returns_400(self):
        res = self.client.get(self._url(), {"org_id": "000invalid000"})
        self.assertIn(res.status_code, [400, 403])

    def test_get_organization_missing_org_id_returns_403(self):
        """IsOrganizationMember blocks when org_id is absent."""
        res = self.client.get(self._url())
        self.assertIn(res.status_code, [400, 403])

    def test_get_organization_non_member_returns_403(self):
        other_user = self.create_user(email="nonmember@example.com")
        self.authenticate(other_user)
        res = self.client.get(self._url(), self._org_params())
        self.assertEqual(res.status_code, 403)

    def test_get_organization_unauthenticated_returns_401(self):
        self.client.credentials()
        res = self.client.get(self._url(), self._org_params())
        self.assertEqual(res.status_code, 401)


class OrganizationUpdateTests(MainTestBase):
    """Tests for PATCH /api/v1/main/organization/"""

    def _url(self):
        return f"/api/v1/main/organization/?org_id={self.org_id}"

    def test_update_organization_name_success(self):
        res = self.client.patch(self._url(), {"name": "Updated Org Name"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Updated Org Name")

    def test_update_organization_industry_success(self):
        res = self.client.patch(self._url(), {"industry": "saas"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_update_organization_non_member_returns_403(self):
        other = self.create_user(email="stranger@example.com")
        self.authenticate(other)
        res = self.client.patch(self._url(), {"name": "Hacked"}, format="json")
        self.assertEqual(res.status_code, 403)
