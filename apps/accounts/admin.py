from django.contrib import admin
from unfold.admin import ModelAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from apps.accounts.models import User, Notification

@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    """Based on Django's UserAdmin so passwords are hashed and edited via the proper form
    (the previous plain ModelAdmin exposed the raw hash field / stored plaintext on add)."""
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    ordering = ('email',)
    list_display = ('email', 'full_name', 'is_active', 'is_staff', 'joined_at')
    search_fields = ('email', 'full_name', 'phone_number')
    list_filter = ('is_active', 'is_staff', 'status')
    date_hierarchy = 'joined_at'
    readonly_fields = ('last_login', 'joined_at')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Profile', {'fields': ('full_name', 'username', 'phone_number', 'avatar', 'gender', 'age',
                                'date_of_birth', 'timezone')}),
        ('Status', {'fields': ('status', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'joined_at')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'password1', 'password2')}),
    )

@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ('user', 'message', 'read', 'created_at')
    search_fields = ('message', 'user__email')
    list_filter = ('read', 'created_at')