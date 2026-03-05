from django.urls import path
from . import views
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)


urlpatterns = [
    path('login/', views.CustomTokenObtainPairView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='verify_email'),
    path('resend-otp/', views.SendOTPView.as_view(), name='resend_otp'),
    path('password-reset/', views.SendOTPView.as_view(), name='password_reset'),
    path('check-otp/', views.CheckOTPView.as_view(), name='password_reset_verify'),
    path('password-reset-confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/update/', views.UpdateProfileView.as_view(), name='profile_update'),
    path('notifications/', views.NotificationListAPIView.as_view(), name='notifications'),
    path('notification-settings/', views.NotificationSettingsAPIView.as_view(), name='notification_settings'),
    path('read-notification/', views.MarkNotificationReadAPIView.as_view(), name='mark_notifications_read'),
    path('read-all-notifications/', views.MarkAllNotificationsReadAPIView.as_view(), name='mark_all_notifications_read'),
    path('delete-notification/', views.DeleteNotificationAPIView.as_view(), name='delete_notifications'),
    path('delete-all-notifications/', views.DeleteAllNotificationsAPIView.as_view(), name='delete_all_notifications'),
    path('delete-account/', views.DeleteAccountView.as_view(), name='delete_account'),
    path('test-notifications/', views.TestNotificationAPIView.as_view(), name='test_notifications'),
    path('contact-us/', views.ContactUsView.as_view(), name='contact_us'),
]
