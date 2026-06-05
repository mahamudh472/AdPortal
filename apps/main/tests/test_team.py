"""
Tests for team management endpoints:
  GET  /api/v1/main/team/?org_id=
  GET  /api/v1/main/team-members/?org_id=
  PATCH/DELETE /api/v1/main/team-member/<id>/?org_id=
  POST /api/v1/main/invite-team-member/?org_id=
  POST /api/v1/main/accept-invitation/<token>/
"""
from unittest.mock import patch

from apps.main.models import OrganizationMember, TeamInvitation
from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"


class TeamStatsTests(MainTestBase):
    """Tests for GET /api/v1/main/team/"""

    def _url(self):
        return f"{BASE}/team/"

    def test_get_team_stats_returns_counts(self):
        member = self.create_user(email="m1@example.com")
        self.add_member(member, self.org, role="MEMBER")
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertIn("total_members", res.data)
        self.assertGreaterEqual(res.data["total_members"], 2)

    def test_get_team_stats_invalid_org_returns_400(self):
        res = self.client.get(self._url(), {"org_id": "bad_org"})
        self.assertIn(res.status_code, [400, 403])


class TeamMemberListTests(MainTestBase):
    """Tests for GET /api/v1/main/team-members/"""

    def _url(self):
        return f"{BASE}/team-members/"

    def test_list_team_members_returns_200(self):
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)

    def test_list_team_members_non_member_returns_403(self):
        other = self.create_user(email="outsider@example.com")
        self.authenticate(other)
        res = self.client.get(self._url(), {"org_id": self.org_id})
        self.assertEqual(res.status_code, 403)


class UpdateDeleteTeamMemberTests(MainTestBase):
    """Tests for PATCH/DELETE /api/v1/main/team-member/<id>/"""

    def _url(self, membership_id):
        return f"{BASE}/team-member/{membership_id}/?org_id={self.org_id}"

    def test_admin_can_update_member_role(self):
        admin = self.create_user(email="admin_team@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        member = self.create_user(email="regular_m@example.com")
        membership = self.add_member(member, self.org, role="MEMBER")
        self.authenticate(admin)
        res = self.client.patch(self._url(membership.id), {"role": "ADMIN"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_cannot_modify_owner_role(self):
        admin = self.create_user(email="admin2@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        owner_membership = OrganizationMember.objects.get(user=self.owner, organization=self.org)
        self.authenticate(admin)
        res = self.client.patch(self._url(owner_membership.id), {"role": "MEMBER"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_admin_can_delete_member(self):
        admin = self.create_user(email="admin3@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        member = self.create_user(email="del_member@example.com")
        membership = self.add_member(member, self.org, role="MEMBER")
        self.authenticate(admin)
        res = self.client.delete(self._url(membership.id))
        self.assertEqual(res.status_code, 204)

    def test_cannot_delete_owner(self):
        admin = self.create_user(email="admin4@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        owner_membership = OrganizationMember.objects.get(user=self.owner, organization=self.org)
        self.authenticate(admin)
        res = self.client.delete(self._url(owner_membership.id))
        self.assertEqual(res.status_code, 403)


class TeamInvitationTests(MainTestBase):
    """Tests for POST /api/v1/main/invite-team-member/"""

    def _url(self):
        return f"{BASE}/invite-team-member/?org_id={self.org_id}"

    @patch("apps.main.services.team.send_team_invitation_email")
    def test_invite_new_user_success(self, mock_email):
        mock_email.return_value = None
        res = self.client.post(
            self._url(), {"email": "newbie@example.com", "role": "MEMBER"}, format="json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            TeamInvitation.objects.filter(
                email="newbie@example.com", organization=self.org
            ).exists()
        )

    @patch("apps.main.services.team.send_team_invitation_email")
    def test_invite_existing_member_returns_400(self, mock_email):
        mock_email.return_value = None
        existing = self.create_user(email="already@example.com")
        self.add_member(existing, self.org)
        res = self.client.post(
            self._url(), {"email": "already@example.com", "role": "MEMBER"}, format="json"
        )
        self.assertEqual(res.status_code, 400)

    def test_invite_as_regular_member_returns_403(self):
        member = self.create_user(email="justamember@example.com")
        self.add_member(member, self.org, role="MEMBER")
        self.authenticate(member)
        res = self.client.post(
            self._url(), {"email": "newbie2@example.com", "role": "MEMBER"}, format="json"
        )
        self.assertEqual(res.status_code, 403)


class InvitationAcceptTests(MainTestBase):
    """Tests for POST /api/v1/main/accept-invitation/<token>/"""

    def _create_invitation(self, email="invitee@example.com"):
        return TeamInvitation.objects.create(
            email=email,
            role="MEMBER",
            organization=self.org,
            invited_by=self.owner,
        )

    @patch("apps.main.services.team.send_account_created_email")
    def test_accept_invitation_creates_new_user(self, mock_email):
        mock_email.return_value = None
        invitation = self._create_invitation("brandnew@example.com")
        res = self.client.post(f"{BASE}/accept-invitation/{invitation.token}/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            OrganizationMember.objects.filter(
                organization=self.org, user__email="brandnew@example.com"
            ).exists()
        )

    def test_accept_invitation_existing_user(self):
        existing = self.create_user(email="existing_inv@example.com")
        invitation = self._create_invitation("existing_inv@example.com")
        self.authenticate(existing)
        res = self.client.post(f"{BASE}/accept-invitation/{invitation.token}/")
        self.assertEqual(res.status_code, 200)

    def test_accept_invitation_invalid_token_returns_400(self):
        res = self.client.post(f"{BASE}/accept-invitation/invalid-token-999/")
        self.assertEqual(res.status_code, 400)

    def test_accept_invitation_already_member_returns_400(self):
        existing = self.create_user(email="alreadyin@example.com")
        self.add_member(existing, self.org)
        invitation = self._create_invitation("alreadyin@example.com")
        self.authenticate(existing)
        res = self.client.post(f"{BASE}/accept-invitation/{invitation.token}/")
        self.assertEqual(res.status_code, 400)
