from rest_framework import serializers
from .models import NotificationSetting, User, Notification
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from main.models import Organization
from finance.models import Subscription
from django.db.models import Sum

class RegisterSerializer(serializers.ModelSerializer):
    timezone = serializers.CharField(required=True)
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'password', 'timezone']
    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
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
        return attrs
    

class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(read_only=True)
    class Meta:
        model = User
        exclude = ['password', 'groups', 'user_permissions']
    
class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email', 'phone_number',]
    


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_active:
            raise serializers.ValidationError("User account is not active.")
        organizations = Organization.objects.filter(memberships__user=self.user, memberships__status='ACTIVE').values_list('snowflake_id', flat=True)
        
        selected_organization = organizations.first() if organizations else None
        subscription = Subscription.objects.filter(organization__snowflake_id=selected_organization, status='active').select_related('plan').first() if selected_organization else None
        if subscription:
            plan_name = subscription.plan.name
            campaign_limit = subscription.plan.get_campaign_limit()
            if campaign_limit != 'Unlimited':
                campaign_limit = int(campaign_limit)
            print(plan_name, campaign_limit)
            campaign_used = subscription.usage_records.filter(feature_key="feature_1").aggregate(total_used=Sum('used'))['total_used'] or 0
    
        data.update(
            {
                'user': SimpleUserSerializer(self.user).data,
                'organizations': list(organizations),
                'current_plan': {
                    'plan_name': plan_name if subscription else None,
                    'campaign_limit': campaign_limit if subscription else None,
                    'campaign_used': campaign_used if subscription else None
                } if subscription else None,
            }
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