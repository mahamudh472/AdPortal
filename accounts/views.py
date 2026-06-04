import random
from django.conf import settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.generics import GenericAPIView, ListAPIView
from accounts.permissions import IsRegularPlatformUser
from accounts.email_utils import send_otp_email, send_welcome_email
from accounts.serializers import (
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
from rest_framework.permissions import IsAuthenticated

class RegisterView(GenericAPIView):
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        user = User.objects.filter(email=request.data.get('email'), is_active=False)
        if user.exists():
            user.delete()
        if serializer.is_valid():
            user = serializer.save(is_active=False)

            otp = str(random.randint(100000, 999999))
            OTP.objects.create(
                user=user,
                code=otp,
                expires_at=timezone.now() + timezone.timedelta(minutes=10)
            )
            
            try:
                send_otp_email(
                    user_email=user.email,
                    user_name=user.full_name or user.email.split('@')[0],
                    otp_code=otp,
                    expiry_minutes=10
                )
                # Send welcome email after successful OTP
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
    serializer_class = VerifyEmailSerializer

    def post(self, request):
        try:
            email= request.data.get('email')
            input_otp = request.data.get('otp')
            
            if not email or not input_otp:
                return Response({"error": "Email and OTP are required"}, status=status.HTTP_400_BAD_REQUEST)
            
            user= User.objects.filter(email=email).first()
            if not user:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            if OTP.objects.filter(user__email=email, code=input_otp).exists():
                otp_record = OTP.objects.get(user__email=email, code=input_otp)
                if otp_record.is_valid():
                    user = otp_record.user
                    user.is_active = True
                    user.save()
                    otp_record.is_used = True
                    otp_record.save()
                    
                    # Send welcome email after email verification
                    try:
                        send_welcome_email(
                            user_email=user.email,
                            user_name=user.full_name or user.email.split('@')[0]
                        )
                    except Exception as e:
                        pass
                    return Response({"message": f"Email {email} successfully verified"}, status=status.HTTP_200_OK)
                    
                else:
                    return Response({"error": "OTP is expired or already used"}, status=status.HTTP_400_BAD_REQUEST)

            
            return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                "error": "Failed to verify email.",
                "detail": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    
class PasswordResetConfirmView(GenericAPIView):
    serializer_class = ResetPasswordConfirmSerializer

    def post(self, request):
        try:
            email= request.data.get('email')
            input_otp = request.data.get('otp')
            new_password = request.data.get('new_password')
            
            if not email or not input_otp or not new_password:
                return Response({"error": "Email, OTP, and new password are required"}, status=status.HTTP_400_BAD_REQUEST)
            
            user= User.objects.filter(email=email).first()
            if not user:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            if OTP.objects.filter(user__email=email, code=input_otp).exists():
                otp_record = OTP.objects.get(user__email=email, code=input_otp)
                if otp_record.is_valid():
                    user = otp_record.user
                    user.set_password(new_password)
                    user.save()
                    otp_record.is_used = True
                    otp_record.save()
                    return Response({"message": f"Password successfully reset for {email}"}, status=status.HTTP_200_OK)
                else:
                    return Response({"error": "OTP is expired or already used"}, status=status.HTTP_400_BAD_REQUEST)

            
            return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                "error": "Failed to reset password.",
                "detail": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class SendOTPView(GenericAPIView):
    def post(self, request):
        email = request.data.get('email')

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User with this email does not exist"}, status=status.HTTP_400_BAD_REQUEST)

        otp = str(random.randint(100000, 999999))
        OTP.objects.create(
            user=user,
            code=otp,
            expires_at=timezone.now() + timezone.timedelta(minutes=10)
        )
                
        try:    
            send_otp_email(
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
    permission_classes = []

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not user:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
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
            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            return Response(
                {"message": "Successfully logged out"},
                status=status.HTTP_205_RESET_CONTENT
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
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
        if not isinstance(notification_ids, list):
            return Response({"error": "notification_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)

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
        if not isinstance(notification_ids, list):
            return Response({"error": "notification_ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)

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
    permission_classes = [IsRegularPlatformUser]

    def delete(self, request):
        user = request.user
        user.delete()
        return Response({"message": "Account deleted successfully"}, status=status.HTTP_200_OK)


class MetaDataDeletionCallbackView(GenericAPIView):
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
        from accounts.services import (
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
        except MetaAppSecretNotConfigured as exc:
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except MetaSignedRequestMissing as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except MetaSignedRequestInvalid as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)


class CheckOTPView(GenericAPIView):
    def post(self, request):
        email = request.data.get('email')
        input_otp = request.data.get('otp')

        if not email or not input_otp:
            return Response({"error": "Email and OTP are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if OTP.objects.filter(user__email=email, code=input_otp).exists():
            otp_record = OTP.objects.get(user__email=email, code=input_otp)
            if otp_record.is_valid():
                return Response({"message": "OTP is valid"}, status=status.HTTP_200_OK)
            else:
                return Response({"error": "OTP is expired or already used"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

class ContactUsView(GenericAPIView):
    permission_classes = []
    serializer_class = ContactUsMessageSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Your message has been received. We'll get back to you shortly."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
