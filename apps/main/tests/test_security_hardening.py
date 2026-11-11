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


class UploadSafetyTests(MainTestBase):
    def _png(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(buf, "PNG")
        buf.seek(0)
        return buf

    def test_real_png_accepted_and_type_detected(self):  # SEC-08
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.main.utils.safe_files import detect_media_type
        f = SimpleUploadedFile("a.png", self._png().read(), content_type="application/x-wrong")
        self.assertEqual(detect_media_type(f), ("IMAGE", "image/png"))

    def test_svg_and_fake_images_rejected(self):  # SEC-08
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.main.utils.safe_files import detect_media_type
        svg = SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", content_type="image/png")
        fake = SimpleUploadedFile("x.png", b"not really an image", content_type="image/png")
        for f in (svg, fake):
            with self.assertRaises(ValidationError):
                detect_media_type(f)

    def test_stored_names_are_unguessable(self):  # SEC-09
        from apps.main.utils.safe_files import report_upload_to
        a = report_upload_to(None, "Weekly_report_Acme_20260101.xlsx")
        self.assertNotIn("Acme", a)
        self.assertTrue(a.endswith(".xlsx"))

    def test_excel_formula_neutralised(self):  # SEC-25
        from apps.main.utils.safe_files import excel_safe
        self.assertEqual(excel_safe('=HYPERLINK("http://x")'), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(excel_safe("normal"), "normal")
        self.assertEqual(excel_safe(5), 5)


class EntitlementTests(MainTestBase):
    def _subscribe(self, **limits):
        from django.utils import timezone
        from apps.finance.models import Plan, PlanFeature, Subscription
        plan = Plan.objects.create(name="starter", price=10, interval="month")
        for k, v in limits.items():
            PlanFeature.objects.create(plan=plan, key=k, value=str(v))
        return Subscription.objects.create(
            organization=self.org, plan=plan, status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def test_suspended_org_is_read_only(self):  # SEC-13
        from apps.main.models import Organization
        Organization.objects.filter(pk=self.org.pk).update(status="SUSPENDED")
        self.assertEqual(
            self.client.get(f"{BASE}/organization/?org_id={self.org_id}").status_code, 200
        )
        res = self.client.post(f"{BASE}/invite-team-member/?org_id={self.org_id}",
                               {"email": "x@example.com", "role": "MEMBER"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_team_member_limit_enforced(self):  # SEC-13
        self._subscribe(team_member_limit=1)  # owner already fills the single seat
        res = self.client.post(f"{BASE}/invite-team-member/?org_id={self.org_id}",
                               {"email": "x@example.com", "role": "MEMBER"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_no_subscription_means_no_enforcement(self):
        from unittest.mock import patch
        with patch("apps.main.services.team.send_team_invitation_email"):
            res = self.client.post(f"{BASE}/invite-team-member/?org_id={self.org_id}",
                                   {"email": "y@example.com", "role": "MEMBER"}, format="json")
        self.assertEqual(res.status_code, 200)

    def test_campaign_limit_helper(self):  # SEC-13
        from apps.finance.entitlements import can_publish_campaign
        from apps.finance.models import UsageRecord
        sub = self._subscribe(campaign_limit=2)
        self.assertTrue(can_publish_campaign(self.org))
        UsageRecord.objects.create(organization=self.org, subscription=sub, feature_key="campaign_limit",
                                   used=2, period_start=sub.current_period_start, period_end=sub.current_period_end)
        self.assertFalse(can_publish_campaign(self.org))


class HousekeepingTests(MainTestBase):
    def test_purge_task_removes_old_otps(self):
        from apps.accounts.models import OTP
        from apps.accounts.tasks import purge_expired_auth_data
        user = self.create_user(email="h@example.com")
        old = OTP.objects.create(user=user, code="123456", expires_at=timezone.now() - timedelta(days=3))
        fresh = OTP.objects.create(user=user, code="654321", expires_at=timezone.now() + timedelta(minutes=5))
        purge_expired_auth_data()
        self.assertFalse(OTP.objects.filter(pk=old.pk).exists())
        self.assertTrue(OTP.objects.filter(pk=fresh.pk).exists())

    def test_log_redaction(self):
        from apps.main.utils.log_filters import redact
        out = redact("GET /x?access_token=EAAB123&a=1 Authorization: Bearer abc.def")
        self.assertNotIn("EAAB123", out)
        self.assertNotIn("abc.def", out)

    def test_snowflake_ids_unique(self):
        from apps.main.models import next_snowflake_id
        ids = {next_snowflake_id() for _ in range(500)}
        self.assertEqual(len(ids), 500)


class HealthTests(MainTestBase):
    def test_probes_are_public(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        res = self.client.get("/readyz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["checks"]["database"], "ok")


class AdminUserTests(MainTestBase):
    def test_admin_add_and_change_user_hash_password(self):  # SEC-28
        from django.test import Client
        su = self.create_user(email="su@example.com", is_staff=True, is_superuser=True)
        c = Client()
        c.force_login(su)
        self.assertEqual(c.get("/admin/accounts/user/add/").status_code, 200)
        res = c.post("/admin/accounts/user/add/", {
            "email": "newadmin@example.com", "password1": "Sup3r-Secret-pass!", "password2": "Sup3r-Secret-pass!",
        })
        self.assertIn(res.status_code, (200, 302))
        created = User.objects.filter(email="newadmin@example.com").first()
        self.assertIsNotNone(created)
        self.assertNotEqual(created.password, "Sup3r-Secret-pass!")
        self.assertTrue(created.check_password("Sup3r-Secret-pass!"))
        self.assertEqual(c.get(f"/admin/accounts/user/{su.pk}/change/").status_code, 200)


class TokenEncryptionTests(MainTestBase):
    def test_tokens_encrypted_at_rest_and_lookup_works(self):  # SEC-12
        from django.db import connection
        integ = self.create_integration("META")
        integ.access_token = "EAAB-secret-token"
        integ.refresh_token = "refresh-secret"
        integ.save()
        with connection.cursor() as cur:
            cur.execute("SELECT access_token, refresh_token FROM main_adintegration WHERE id=%s", [integ.id])
            raw_a, raw_r = cur.fetchone()
        self.assertTrue(raw_a.startswith("enc1:"))
        self.assertNotIn("EAAB", raw_a)
        self.assertTrue(raw_r.startswith("enc1:"))
        integ.refresh_from_db()
        self.assertEqual(integ.access_token, "EAAB-secret-token")
        self.assertEqual(AdIntegration.find_by_token("EAAB-secret-token").pk, integ.pk)
        self.assertIsNone(AdIntegration.find_by_token("nope"))

    def test_legacy_plaintext_still_readable(self):
        from django.db import connection
        integ = self.create_integration("TIKTOK")
        with connection.cursor() as cur:
            cur.execute("UPDATE main_adintegration SET access_token='plain-old' WHERE id=%s", [integ.id])
        integ.refresh_from_db()
        self.assertEqual(integ.access_token, "plain-old")

    def test_update_via_queryset_is_encrypted(self):
        from django.db import connection
        integ = self.create_integration("META")
        AdIntegration.objects.filter(pk=integ.pk).update(access_token="new-token")
        with connection.cursor() as cur:
            cur.execute("SELECT access_token FROM main_adintegration WHERE id=%s", [integ.id])
            self.assertTrue(cur.fetchone()[0].startswith("enc1:"))


class PrivateReportTests(MainTestBase):
    def _report(self):
        from django.core.files.base import ContentFile
        from apps.analysis.models import Report
        r = Report.objects.create(organization=self.org, name="W.xlsx", report_type="weekly", status="COMPLETED")
        r.file.save("W.xlsx", ContentFile(b"PK-fake-xlsx"), save=True)
        return r

    def test_report_list_exposes_authenticated_url_not_media(self):  # SEC-09
        self._report()
        res = self.client.get(f"/api/v1/analysis/reports/?org_id={self.org_id}")
        file_url = res.json()["results"][0]["file"]
        self.assertIn("/analysis/reports/", file_url)
        self.assertNotIn("/media/", file_url)

    def test_member_downloads_outsider_and_anonymous_cannot(self):
        r = self._report()
        url = f"/api/v1/analysis/reports/{r.pk}/download/report.xlsx?org_id={self.org_id}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(b"".join(res.streaming_content), b"PK-fake-xlsx")
        outsider = self.create_user(email="o2@example.com")
        self.create_organization(outsider, name="Other2")
        self.authenticate(outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.credentials()
        self.assertEqual(self.client.get(url).status_code, 401)


class RefreshCookieTests(MainTestBase):
    def _login(self, cookie_mode):
        self.create_user(email="ck@example.com")
        self.client.credentials()
        headers = {"HTTP_X_AUTH_MODE": "cookie"} if cookie_mode else {}
        return self.client.post("/api/v1/accounts/login/", {"email": "ck@example.com", "password": "StrongPass123!"},
                                format="json", **headers)

    def test_legacy_mode_unchanged(self):
        res = self._login(False)
        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res.data["refresh"], "cookie")
        self.assertNotIn("refresh_token", res.cookies)

    def test_cookie_mode_hides_refresh_from_body_and_refreshes(self):
        res = self._login(True)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["refresh"], "cookie")
        morsel = res.cookies["refresh_token"]
        self.assertTrue(morsel["httponly"])
        self.assertTrue(morsel.value)
        # refresh with only the cookie (+ placeholder body)
        self.client.cookies["refresh_token"] = morsel.value
        r2 = self.client.post("/api/v1/accounts/token/refresh/", {"refresh": "cookie"}, format="json",
                              HTTP_X_AUTH_MODE="cookie")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("access", r2.data)
        self.assertEqual(r2.data["refresh"], "cookie")
        self.assertNotEqual(r2.cookies["refresh_token"].value, morsel.value)  # rotated

    def test_logout_blacklists_cookie_token(self):
        res = self._login(True)
        access = res.data["access"]
        self.client.cookies["refresh_token"] = res.cookies["refresh_token"].value
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        out = self.client.post("/api/v1/accounts/logout/", {"refresh_token": "cookie"}, format="json")
        self.assertEqual(out.status_code, 205)
        self.client.credentials()
        again = self.client.post("/api/v1/accounts/token/refresh/", {}, format="json", HTTP_X_AUTH_MODE="cookie")
        self.assertIn(again.status_code, (400, 401))
