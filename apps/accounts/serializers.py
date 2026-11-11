from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from urllib3 import request
from .models import NotificationSetting, User, Notification, ContactUsMessage
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from apps.main.models import Organization
from apps.finance.models import Subscription
from django.db.models import Sum

class RegisterSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField(required=True)
    class Meta:
        model = User
        fields = ['id', 'full_name', 'email', 'password', 'timezone']
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, attrs):
        candidate = User(email=attrs.get('email'), full_name=attrs.get('full_name'))
        try:
            validate_password(attrs.get('password'), candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            full_name=validated_data.get('full_name', ''),
            is_active=False,
            timezone=validated_data['timezone']
        )
        user.set_password(validated_data['password'])
        user.save()
        
        return user

    

class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

class ResetPasswordConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True)
    

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError("New passwords do not match")
        request = self.context.get('request')
        try:
            validate_password(attrs['new_password'], getattr(request, 'user', None))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        return attrs
    

class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(read_only=True)
    class Meta:
        model = User
        # Whitelist only self-editable profile fields. Privileged / system fields
        # (is_staff, is_superuser, is_active, status, last_login, ...) must never
        # be writable through the profile endpoint.
        fields = [
            'id', 'email', 'username', 'full_name', 'phone_number', 'avatar',
            'gender', 'age', 'date_of_birth', 'timezone', 'joined_at',
        ]
        read_only_fields = ['id', 'joined_at']
    
class SimpleUserSerializer(serializers.ModelSerializer):
    is_admin = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ['id', 'full_name', 'email', 'phone_number', 'is_admin', 'avatar']
    
    def get_is_admin(self, obj):
        if obj.is_superuser or obj.is_staff:
            return True
        return False


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_active:
            raise serializers.ValidationError("User account is not active.")
        organizations = Organization.objects.filter(memberships__user=self.user, memberships__status='ACTIVE').values_list('snowflake_id', 'name')
        owned_org = Organization.objects.filter(memberships__user=self.user, memberships__status='ACTIVE', memberships__role='OWNER').exists()
        if not owned_org and not organizations.exists():
            raise serializers.ValidationError("User does not belong to any active organization.")
        if owned_org:
            selected_organization = Organization.objects.filter(memberships__user=self.user, memberships__status='ACTIVE', memberships__role='OWNER').values_list('snowflake_id', flat=True).first()
        else:
            selected_organization = organizations.values_list('snowflake_id', flat=True).first() if organizations.exists() else None
        
        subscription = Subscription.objects.filter(organization__snowflake_id=selected_organization, status='active').select_related('plan').last() if selected_organization else None
        if subscription:
            plan_name = subscription.plan.name
            # Returns int for a hard limit, or None when unlimited
            limit = subscription.plan.get_campaign_limit()
            campaign_limit = 'Unlimited' if limit is None else limit
            campaign_used = subscription.usage_records.filter(feature_key="campaign_limit").aggregate(total_used=Sum('used'))['total_used'] or 0
    
        data.update(
            {
                'user': SimpleUserSerializer(self.user, context={"request": self.context.get('request')}).data,
                'organizations': list(organizations),
                'current_plan': {
                    'plan_name': plan_name if subscription else None,
                    'campaign_limit': campaign_limit if subscription else None,
                    'campaign_used': campaign_used if subscription else None
                } if subscription else None, }
        )
        return data


class NotificationSerializer(serializers.ModelSerializer):

    class Meta:
         model = Notification
         fields = "__all__"

class NotificationSettingsSerializer(serializers.ModelSerializer):

    class Meta:
         model = NotificationSetting
         fields = ['campaign_performance', 'budget_alerts', 'weekly_performance_summary', 'ai_recommendations', 'team_activity']

class ContactUsMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactUsMessage
        fields = "__all__"
