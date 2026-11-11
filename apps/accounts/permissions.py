from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.main.models import OrganizationMember, Organization

def _blocked_by_suspension(permission, request, organization) -> bool:
    """Suspended organizations are read-only (audit SEC-13)."""
    if request.method not in SAFE_METHODS and organization.status == 'SUSPENDED':
        permission.message = "This organization is suspended. Contact support."
        return True
    return False


class IsRegularPlatformUser(BasePermission):
    """
    Composite permission:
    - authenticated
    - not platform admin
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if user.is_staff or user.is_superuser:
            return False

        return True

class IsOrganizationMember(BasePermission):
    """
    Permission to check if the user is a member of the organization specified in the request header.
    """

    def has_permission(self, request, view):
        user = request.user
        org_id = request.query_params.get("org_id")

        if not user or not user.is_authenticated:
            return False

        if not org_id:
            return False

        try:
            organization = Organization.objects.get(snowflake_id=org_id)
        except Organization.DoesNotExist:
            return False

        if _blocked_by_suspension(self, request, organization):
            return False

        return OrganizationMember.objects.filter(
            user=user, organization=organization, status='ACTIVE'
        ).exists()

class IsOrgAdminForWrites(BasePermission):
    """
    Read-only methods: any active member of the organization.
    Write methods: only ADMIN / OWNER of the organization.
    Use together with IsOrganizationMember.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        org_id = request.query_params.get("org_id")
        if not org_id:
            return False
        return OrganizationMember.objects.filter(
            user=user,
            organization__snowflake_id=org_id,
            status='ACTIVE',
            role__in=['ADMIN', 'OWNER'],
        ).exists()

class IsAdminOrOwnerOfOrganization(BasePermission):
    """
    Permission to check if the user is an admin or owner of the organization specified in the request header.
    """

    def has_permission(self, request, view):
        user = request.user
        org_id = request.query_params.get("org_id")

        if not user or not user.is_authenticated:
            return False

        if not org_id:
            return False

        try:
            organization = Organization.objects.get(snowflake_id=org_id)
        except Organization.DoesNotExist:
            return False

        if _blocked_by_suspension(self, request, organization):
            return False

        return OrganizationMember.objects.filter(
            user=user,
            organization=organization,
            status='ACTIVE',
            role__in=['ADMIN', 'OWNER']
        ).exists()
