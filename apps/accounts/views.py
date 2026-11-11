from django.conf import settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import GenericAPIView, ListAPIView
from apps.accounts.permissions import IsRegularPlatformUser
from apps.accounts.email_utils import send_welcome_email
from apps.accounts.tasks import send_otp_email_task
from apps.accounts.serializers import (
    CustomTokenObtainPairSerializer,
    NotificationSettingsSerializer, 
    ResetPasswordConfirmSerializer,
    RegisterSerializer,
    SimpleUserSerializer,
    UserSerializer, 
    VerifyEmailSerializer,
    ChangePasswordSerializer,
    NotificationSerializer,
    ContactUsMessageSerializer
)
from rest_framework.pagination import PageNumberPagination
from .models import NotificationSetting, User, OTP, Notification
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .otp import issue_otp, consume_otp, check_otp

class RegisterView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        user = User.objects.filter(email=request.data.get('email'), is_active=False)
        if user.exists():
            user.delete()
        if serializer.is_valid():
            user = serializer.save(is_active=False)

            otp = issue_otp(user)

            try:
                send_otp_email_task.delay(
                    user_email=user.email,
                    user_name=user.full_name or user.email.split('@')[0],
                    otp_code=otp,
                    expiry_minutes=10
                )
                return Response({"message": "Otp sent successfully"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                # Log the error for debugging
                # Still return success but with different message
                return Response({
                    "message": "Account created successfully. Email service temporarily unavailable.",
                    "otp": otp if settings.DEBUG else None  # Only show OTP in debug mode
                }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifyEmailView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = VerifyEmailSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    def post(self, request):
        email = request.data.get('email')
        input_otp = request.data.get('otp')

        if not email or not input_otp:
            return Response({"error": "Email and OTP are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

        ok, error = consume_otp(user, input_otp)
        if not ok:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = True
        user.save(update_fields=['is_active'])
        try:
            send_welcome_email(
                user_email=user.email,
                user_name=user.full_name or user.email.split('@')[0]
            )
        except Exception:
            pass
        return Response({"message": f"Email {email} successfully verified"}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ResetPasswordConfirmSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    def post(self, request):
        email = request.data.get('email')
        input_otp = request.data.get('otp')
        new_password = request.data.get('new_password')

        if not email or not input_otp or not new_password:
            return Response({"error": "Email, OTP, and new password are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate the password first so a weak password doesn't burn the OTP.
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        ok, error = consume_otp(user, input_otp)
        if not ok:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
        return Response({"message": f"Password successfully reset for {email}"}, status=status.HTTP_200_OK)


class ProfileView(GenericAPIView):
    serializer_class = SimpleUserSerializer
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        serializer = self.serializer_class(user, context={"request": request})

        return Response(serializer.data, status=status.HTTP_200_OK)

class UpdateProfileView(GenericAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsRegularPlatformUser]

    def patch(self, request):
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'success': 'Profile updated successfully'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


REFRESH_COOKIE = 'refresh_token'
COOKIE_SENTINEL = 'cookie'


def _cookie_mode(request) -> bool:
    return request.headers.get('X-Auth-Mode', '').lower() == 'cookie'


def _set_refresh_cookie(response, refresh_value):
    response.set_cookie(
        REFRESH_COOKIE, refresh_value,
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        httponly=True,
        secure=settings.USE_HTTPS,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path='/api/v1/accounts/',
    )


def _clear_refresh_cookie(response):
    response.delete_cookie(REFRESH_COOKIE, path='/api/v1/accounts/', samesite=settings.AUTH_COOKIE_SAMESITE)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Login. With ``X-Auth-Mode: cookie`` the refresh token travels only in an HttpOnly
    cookie (invisible to JavaScript / XSS) and the body carries a placeholder instead."""
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200 and _cookie_mode(request) and response.data.get('refresh'):
            _set_refresh_cookie(response, response.data['refresh'])
            response.data['refresh'] = COOKIE_SENTINEL
        return response


class CookieTokenRefreshView(TokenRefreshView):
    """Refresh using the HttpOnly cookie (cookie mode) or the request body (legacy)."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request, *args, **kwargs):
        cookie_mode = _cookie_mode(request)
        if cookie_mode:
            body_value = request.data.get('refresh')
            if not body_value or body_value == COOKIE_SENTINEL:
                data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
                data['refresh'] = request.COOKIES.get(REFRESH_COOKIE, '')
                request._full_data = data
        response = super().post(request, *args, **kwargs)
        if cookie_mode:
            if response.status_code == 200 and response.data.get('refresh'):
                _set_refresh_cookie(response, response.data['refresh'])
                response.data['refresh'] = COOKIE_SENTINEL
            elif response.status_code in (400, 401):
                _clear_refresh_cookie(response)
        return response


class SendOTPView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_send'

    def post(self, request):
        email = request.data.get('email')

        user = User.objects.filter(email=email).first()
        if not user:
            # Same answer as the success path: don't reveal which e-mails are registered.
            return Response({"message": "Otp sent successfully"}, status=status.HTTP_200_OK)

        otp = issue_otp(user)

        try:
            send_otp_email_task.delay(
                user_email=user.email,
                user_name=user.full_name or user.email.split('@')[0],
                otp_code=otp,
                expiry_minutes=10
            )
            return Response({"message": "Otp sent successfully"}, status=status.HTTP_200_OK)
        
        except Exception as e:
            # Still return success but with different message
            return Response({
                "message": "OTP created successfully. Email service temporarily unavailable."
            }, status=status.HTTP_200_OK)

class ChangePasswordView(GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = request.user
            if not user:
                return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
            if not user.check_password(serializer.validated_data.get('old_password')):
                return Response({"error": "Old password is incorrect"}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(serializer.validated_data.get('new_password'))
            user.save()
            return Response({"message": "Password changed successfully"}, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if not refresh_token or refresh_token == COOKIE_SENTINEL:
                refresh_token = request.COOKIES.get(REFRESH_COOKIE)
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            response = Response(
                {"message": "Successfully logged out"},
                status=status.HTTP_205_RESET_CONTENT
            )
            _clear_refresh_cookie(response)
            return response
        except Exception:
            return Response(
                {"error": "Invalid or expired refresh token"},
                status=status.HTTP_400_BAD_REQUEST
            )
class NotifcationListPagination(PageNumberPagination):
    page_size = 10
    max_page_size = 100
    page_query_param = "page"
    page_size_query_param = "page_size"

class NotificationListAPIView(ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = NotifcationListPagination

    def get_queryset(self):
        # filter with read query param if provided
        read_param = self.request.query_params.get('read')
        if read_param is not None:
            if read_param.lower() == 'true':
                return Notification.objects.filter(user=self.request.user, read=True).order_by('-created_at')
            elif read_param.lower() == 'false':
                return Notification.objects.filter(user=self.request.user, read=False).order_by('-created_at')
            else:
                return Notification.objects.filter(user=self.request.user).order_by('-created_at')
        notifications = Notification.objects.filter(user=self.request.user).order_by('-created_at')
        return notifications
    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        unread_count = self.get_queryset().filter(read=False).count()
        response.data['unread_count'] = unread_count
        return response

class MarkNotificationReadAPIView(GenericAPIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request):
        notification_ids = request.data.get('notification_ids', [])
        if not isinstance(notification_ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in notification_ids
        ):
            return Response({"error": "notification_ids must be a list of integers"}, status=status.HTTP_400_BAD_REQUEST)

        notifications = Notification.objects.filter(id__in=notification_ids, user=request.user)
        updated_count = notifications.update(read=True)

        return Response({"message": f"{updated_count} notifications marked as read"}, status=status.HTTP_200_OK)

class MarkAllNotificationsReadAPIView(GenericAPIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request):
        notifications = Notification.objects.filter(user=request.user, read=False)
        updated_count = notifications.update(read=True)

        return Response({"message": f"All {updated_count} notifications marked as read"}, status=status.HTTP_200_OK)

class DeleteNotificationAPIView(GenericAPIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request):
        notification_ids = request.data.get('notification_ids', [])
        if not isinstance(notification_ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in notification_ids
        ):
            return Response({"error": "notification_ids must be a list of integers"}, status=status.HTTP_400_BAD_REQUEST)

        notifications = Notification.objects.filter(id__in=notification_ids, user=request.user)
        deleted_count, _ = notifications.delete()

        return Response({"message": f"{deleted_count} notifications deleted"}, status=status.HTTP_200_OK)

class DeleteAllNotificationsAPIView(GenericAPIView):
    permission_classes = [IsRegularPlatformUser]

    def post(self, request):
        notifications = Notification.objects.filter(user=request.user)
        deleted_count, _ = notifications.delete()

        return Response({"message": f"All {deleted_count} notifications deleted"}, status=status.HTTP_200_OK)

class TestNotificationAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not settings.DEBUG:
            from django.http import Http404
            raise Http404
        user = request.user
        Notification.objects.create(
            user=user,
            message="This is a test notification."
        )
        return Response({"message": "Test notification created"}, status=status.HTTP_201_CREATED)

class NotificationSettingsAPIView(GenericAPIView):
    serializer_class = NotificationSettingsSerializer
    permission_classes = [IsRegularPlatformUser]
    def get(self, request):
        user = request.user
        settings, created = NotificationSetting.objects.get_or_create(user=user)
        serializer = self.serializer_class(settings)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        user = request.user
        settings, created = NotificationSetting.objects.get_or_create(user=user)
        serializer = self.serializer_class(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class DeleteAccountView(GenericAPIView):
    """DELETE /accounts/delete-account/  body: {"password": "..."}

    Safeguards (audit SEC-15): re-authentication with the password, refuses to delete a
    user who owns an organization that still has other active members (ownership must
    be handled first), and cancels the Stripe subscriptions of organizations that are
    deleted with the account so billing stops.
    """
    permission_classes = [IsRegularPlatformUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def delete(self, request):
        from apps.main.models import Organization, OrganizationMember

        user = request.user
        password = request.data.get('password')
        if not password:
            return Response({"error": "Password confirmation is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.check_password(password):
            return Response({"error": "Incorrect password."}, status=status.HTTP_400_BAD_REQUEST)

        owned = Organization.objects.filter(owner=user)
        for org in owned:
            if OrganizationMember.objects.filter(organization=org, status='ACTIVE').exclude(user=user).exists():
                return Response(
                    {"error": f'You still own "{org.name}" which has other members. '
                              "Transfer ownership or remove the members before deleting your account."},
                    status=status.HTTP_409_CONFLICT,
                )

        self._cancel_stripe_subscriptions(owned)
        user.delete()
        return Response({"message": "Account deleted successfully"}, status=status.HTTP_200_OK)

    @staticmethod
    def _cancel_stripe_subscriptions(organizations):
        import logging
        import stripe
        from apps.finance.models import Subscription
        log = logging.getLogger(__name__)
        subs = Subscription.objects.filter(
            organization__in=organizations, status__in=['active', 'trialing', 'past_due'],
        ).exclude(stripe_subscription_id__isnull=True).exclude(stripe_subscription_id='')
        for sub in subs:
            try:
                stripe.Subscription.cancel(sub.stripe_subscription_id)
            except Exception:
                log.exception("Failed to cancel Stripe subscription %s during account deletion", sub.stripe_subscription_id)


class MetaDataDeletionCallbackView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    """
    Meta (Facebook) Data Deletion Callback — thin HTTP adapter.

    Delegates all business logic to ``accounts.services.handle_meta_data_deletion``.

    Endpoint : POST /api/v1/accounts/delete-data/
    Auth     : None (public — Meta calls this directly)
    Docs     : https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback
    """
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        from apps.accounts.services import (
            MetaAppSecretNotConfigured,
            MetaSignedRequestInvalid,
            MetaSignedRequestMissing,
            handle_meta_data_deletion,
        )

        signed_request = (
            request.data.get("signed_request")
            or request.POST.get("signed_request")
        )

        try:
            result = handle_meta_data_deletion(signed_request)
        except MetaAppSecretNotConfigured:
            return Response({"error": "Service misconfigured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except MetaSignedRequestMissing as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except MetaSignedRequestInvalid as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class CheckOTPView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp'

    def post(self, request):
        email = request.data.get('email')
        input_otp = request.data.get('otp')

        if not email or not input_otp:
            return Response({"error": "Email and OTP are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)

        ok, error = check_otp(user, input_otp)
        if not ok:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "OTP is valid"}, status=status.HTTP_200_OK)

class ContactUsView(GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'contact'
    serializer_class = ContactUsMessageSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Your message has been received. We'll get back to you shortly."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
