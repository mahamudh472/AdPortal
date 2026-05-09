from django.contrib import admin
from unfold.admin import ModelAdmin
from accounts.models import User, Notification

@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ('email', 'full_name', 'is_active', 'is_staff', 'joined_at')
    search_fields = ('email', 'full_name', 'phone_number')
    list_filter = ('is_active', 'is_staff', 'status')
    date_hierarchy = 'joined_at'

@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ('user', 'message', 'read', 'created_at')
    search_fields = ('message', 'user__email')
    list_filter = ('read', 'created_at')