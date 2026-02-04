from rest_framework.permissions import BasePermission
from main.models import OrganizationMember, Organization

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

        if not org_id:
            return False

        try:
            organization = Organization.objects.get(snowflake_id=org_id)
        except Organization.DoesNotExist:
            return False

        return OrganizationMember.objects.filter(user=user, organization=organization).exists()    

class IsAdminOrOwnerOfOrganization(BasePermission):
    """
    Permission to check if the user is an admin or owner of the organization specified in the request header.
    """

    def has_permission(self, request, view):
        user = request.user
        org_id = request.query_params.get("org_id")

        if not org_id:
            return False

        try:
            organization = Organization.objects.get(snowflake_id=org_id)
        except Organization.DoesNotExist:
            return False

        return OrganizationMember.objects.filter(
            user=user,
            organization=organization,
            role__in=['admin', 'owner']
        ).exists()
