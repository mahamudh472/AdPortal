from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Plan, PlanFeature, Subscription, Payment, UsageRecord

@admin.register(Plan)
class PlanAdmin(ModelAdmin):
    list_display = ('name', 'price', 'currency', 'interval', 'is_active', 'is_custom', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active', 'is_custom', 'interval')

@admin.register(PlanFeature)
class PlanFeatureAdmin(ModelAdmin):
    list_display = ('plan', 'key', 'value')
    search_fields = ('plan__name', 'key', 'value')
    list_filter = ('plan',)
    
@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ('organization', 'plan', 'status', 'created_at')
    search_fields = ('organization__name', 'plan__name', 'status')
    list_filter = ('status', 'created_at')
    date_hierarchy = 'created_at'

@admin.register(Payment)
class PaymentAdmin(ModelAdmin):
    list_display = ('organization', 'amount', 'currency', 'status', 'paid_at', 'created_at')
    search_fields = ('organization__name', 'status')
    list_filter = ('status', 'currency')
    date_hierarchy = 'paid_at'

@admin.register(UsageRecord)
class UsageRecordAdmin(ModelAdmin):
    pass
