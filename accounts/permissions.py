from rest_framework.permissions import BasePermission
from rest_framework.permissions import IsAuthenticated

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