"""Regression tests for the security audit fixes (docs/CODEBASE_AUDIT.md SEC-01..05)."""
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import User
from apps.main.models import AdIntegration, OrganizationMember, TeamInvitation
from apps.main.tests.base import MainTestBase

BASE = "/api/v1/main"


class PrivilegeEscalationTests(MainTestBase):
    def test_profile_update_cannot_set_staff_or_superuser(self):  # SEC-01
        user = self.create_user(email="p@example.com")
        self.authenticate(user)
        res = self.client.patch(
            "/api/v1/accounts/profile/update/",
            {"is_staff": True, "is_superuser": True, "is_active": False, "full_name": "New"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertEqual(user.full_name, "New")

    def test_outsider_cannot_touch_other_org_integrations(self):  # SEC-02
        self.create_integration("META")
        outsider = self.create_user(email="out@example.com")
        self.create_organization(outsider, name="Other")
        self.authenticate(outsider)
        for method, path, data in [
            ("get", "get-meta-pages/", None),
            ("post", "select-meta-page/", {"page_id": "1"}),
            ("post", "disconnect-integration/", {"platform": "META"}),
        ]:
            res = getattr(self.client, method)(
                f"{BASE}/{path}?org_id={self.org_id}", data, format="json"
            )
            self.assertIn(res.status_code, (400, 403), path)
        self.assertTrue(AdIntegration.objects.filter(organization=self.org).exists())

    def test_member_cannot_disconnect_or_rename_org(self):  # SEC-04
        self.create_integration("META")
        member = self.create_user(email="mem@example.com")
        self.add_member(member, self.org, role="MEMBER")
        self.authenticate(member)
        res = self.client.post(
            f"{BASE}/disconnect-integration/?org_id={self.org_id}", {"platform": "META"}, format="json"
        )
        self.assertEqual(res.status_code, 403)
        res = self.client.patch(
            f"{BASE}/organization/?org_id={self.org_id}", {"name": "Hacked"}, format="json"
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_cannot_change_org_status_or_campaign_status(self):  # SEC-04
        admin = self.create_user(email="adm@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        self.authenticate(admin)
        self.client.patch(
            f"{BASE}/organization/?org_id={self.org_id}", {"status": "SUSPENDED"}, format="json"
        )
        self.org.refresh_from_db()
        self.assertEqual(self.org.status, "ACTIVE")
        campaign = self.create_campaign(status="ACTIVE")
        self.client.patch(
            f"{BASE}/campaign/{campaign.id}/?org_id={self.org_id}", {"status": "ARCHIVED"}, format="json"
        )
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, "ACTIVE")

    def test_admin_cannot_promote_self_to_owner(self):  # SEC-05
        admin = self.create_user(email="adm2@example.com")
        membership = self.add_member(admin, self.org, role="ADMIN")
        self.authenticate(admin)
        res = self.client.patch(
            f"{BASE}/team-member/{membership.id}/?org_id={self.org_id}", {"role": "OWNER"}, format="json"
        )
        self.assertIn(res.status_code, (400, 403))
        membership.refresh_from_db()
        self.assertEqual(membership.role, "ADMIN")

    def test_invalid_role_rejected(self):  # SEC-05
        admin = self.create_user(email="adm3@example.com")
        self.add_member(admin, self.org, role="ADMIN")
        member = self.create_user(email="m3@example.com")
        mm = self.add_member(member, self.org, role="MEMBER")
        self.authenticate(admin)
        res = self.client.patch(
            f"{BASE}/team-member/{mm.id}/?org_id={self.org_id}", {"role": "SUPERBOSS"}, format="json"
        )
        self.assertEqual(res.status_code, 400)


class LegacyMetaEndpointScopeTests(MainTestBase):
    def test_cannot_act_on_other_orgs_campaign(self):  # SEC-03
        other_owner = self.create_user(email="oo@example.com")
        other_org = self.create_organization(other_owner, name="Other")
        from apps.main.models import UnifiedCampaign
        foreign = UnifiedCampaign.objects.create(
            organization=other_org, name="x", status="ACTIVE", objective="TRAFFIC"
        )
        for path in ("meta/create-ad/", "meta/update-campaign/", "meta/delete-ad/", "create-platform-campaign/"):
            res = self.client.post(
                f"{BASE}/{path}?org_id={self.org_id}", {"campaign_id": foreign.id}, format="json"
            )
            self.assertEqual(res.status_code, 404, path)


class InvitationExpiryTests(MainTestBase):
    def test_expired_invitation_rejected(self):
        inv = TeamInvitation.objects.create(
            organization=self.org, email="new@example.com", role="MEMBER", invited_by=self.owner
        )
        TeamInvitation.objects.filter(pk=inv.pk).update(created_at=timezone.now() - timedelta(days=8))
        self.client.credentials()
        res = self.client.post(f"{BASE}/accept-invitation/{inv.token}/")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())


class AuthHardeningTests(MainTestBase):
    def test_weak_password_rejected_on_register(self):  # SEC password validators
        res = self.client.post(
            "/api/v1/accounts/register/",
            {"email": "w@example.com", "password": "1", "full_name": "W", "timezone": "UTC"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("password", res.data)

    def test_anonymous_change_password_is_401(self):
        self.client.credentials()
        res = self.client.post(
            "/api/v1/accounts/change-password/",
            {"old_password": "a", "new_password": "b", "confirm_password": "b"},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_otp_locks_after_repeated_failures(self):  # SEC-06
        from apps.accounts.otp import issue_otp, MAX_FAILED_ATTEMPTS
        user = self.create_user(email="otp@example.com", active=False)
        code = issue_otp(user)
        wrong = "000000" if code != "000000" else "111111"
        self.client.credentials()
        for _ in range(MAX_FAILED_ATTEMPTS):
            res = self.client.post("/api/v1/accounts/verify-email/", {"email": user.email, "otp": wrong}, format="json")
            self.assertEqual(res.status_code, 400)
        # Even the correct code is refused once locked.
        res = self.client.post("/api/v1/accounts/verify-email/", {"email": user.email, "otp": code}, format="json")
        self.assertEqual(res.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_new_otp_invalidates_old_and_cannot_replay(self):
        from apps.accounts.otp import issue_otp
        user = self.create_user(email="otp2@example.com", active=False)
        old = issue_otp(user)
        new = issue_otp(user)
        self.client.credentials()
        if old != new:
            r = self.client.post("/api/v1/accounts/verify-email/", {"email": user.email, "otp": old}, format="json")
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/accounts/verify-email/", {"email": user.email, "otp": new}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/api/v1/accounts/verify-email/", {"email": user.email, "otp": new}, format="json")
        self.assertEqual(r.status_code, 400)


class PublicSurfaceTests(MainTestBase):
    def test_schema_requires_staff(self):  # SEC-27
        self.client.credentials()
        self.assertIn(self.client.get("/api/schema/").status_code, (401, 403))
        self.authenticate(self.owner)
        self.assertEqual(self.client.get("/api/schema/").status_code, 403)

    def test_contact_message_length_capped(self):  # SEC-30
        self.client.credentials()
        res = self.client.post(
            "/api/v1/accounts/contact-us/",
            {"name": "a", "email": "a@example.com", "subject": "s", "message": "x" * 6000},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_admin_router_root_not_public(self):
        self.client.credentials()
        self.assertIn(self.client.get("/api/v1/admin/").status_code, (401, 403))
