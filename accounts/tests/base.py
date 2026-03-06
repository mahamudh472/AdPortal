"""
Shared base test helpers for AdPortal test suite.

Usage:
    from accounts.tests.base import AdPortalTestBase
"""
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from django.test import TestCase

from accounts.models import User, OTP
from main.models import Organization, OrganizationMember


class AdPortalTestBase(TestCase):
    """
    Base class that all AdPortal test cases inherit from.
    Provides factory helpers and a pre-configured APIClient.
    """

    def setUp(self):
        self.client = APIClient()

    # ──────────────────────────────────────────────────
    # User factories
    # ──────────────────────────────────────────────────

    def create_user(
        self,
        email="testuser@example.com",
        password="StrongPass123!",
        full_name="Test User",
        active=True,
        is_staff=False,
        is_superuser=False,
    ):
        user = User.objects.create_user(
            email=email,
            password=password,
            full_name=full_name,
            is_active=active,
            is_staff=is_staff,
            is_superuser=is_superuser,
            timezone="UTC",
        )
        return user

    def create_admin_user(self, email="admin@example.com", password="AdminPass123!"):
        return self.create_user(
            email=email,
            password=password,
            full_name="Admin User",
            is_staff=True,
        )

    # ──────────────────────────────────────────────────
    # JWT helpers
    # ──────────────────────────────────────────────────

    def get_tokens_for_user(self, user):
        """Returns (access_token_str, refresh_token_str)."""
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token), str(refresh)

    def authenticate(self, user):
        """Sets APIClient credentials for the given user."""
        access, _ = self.get_tokens_for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return access

    # ──────────────────────────────────────────────────
    # Organization / membership factories
    # ──────────────────────────────────────────────────

    def create_organization(self, owner, name="Test Org"):
        org = Organization.objects.create(owner=owner, name=name)
        # Auto-create OWNER membership
        OrganizationMember.objects.create(
            user=owner,
            organization=org,
            role="OWNER",
            status="ACTIVE",
        )
        return org

    def add_member(self, user, organization, role="MEMBER", status="ACTIVE"):
        return OrganizationMember.objects.create(
            user=user,
            organization=organization,
            role=role,
            status=status,
        )

    # ──────────────────────────────────────────────────
    # OTP factory
    # ──────────────────────────────────────────────────

    def create_otp(self, user, code="123456", expired=False, used=False):
        delta = -1 if expired else 10  # minutes
        otp = OTP.objects.create(
            user=user,
            code=code,
            expires_at=timezone.now() + timezone.timedelta(minutes=delta),
            is_used=used,
        )
        return otp
