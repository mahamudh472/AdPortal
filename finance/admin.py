from django.contrib import admin
from .models import Plan, PlanFeature, Subscription

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'currency', 'interval', 'is_active', 'is_custom', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active', 'is_custom', 'interval')

@admin.register(PlanFeature)
class PlanFeatureAdmin(admin.ModelAdmin):
    list_display = ('plan', 'key', 'value')
    search_fields = ('plan__name', 'key', 'value')
    list_filter = ('plan',)
    
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_start', 'current_period_end', 'cancel_at_period_end', 'created_at')
    search_fields = ('user__username', 'plan__name', 'status')
    list_filter = ('status', 'cancel_at_period_end')
    date_hierarchy = 'created_at'
