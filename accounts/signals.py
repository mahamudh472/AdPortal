from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import User, Notification
from main.models import Organization, OrganizationMember, OrganizationRole
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

@receiver(post_save, sender=User)
def user_creation_handler(sender, instance, created, **kwargs):
	if created:
		organization = Organization.objects.create(
			owner=instance
		)
		OrganizationMember.objects.create(
			user=instance,
			organization=organization,
			role=OrganizationRole.OWNER,
			status='ACTIVE'
		)
		# Notify all admins of the new signup (respects AdminNotificationSettings)
		from accounts.notifications import notify_admins
		notify_admins(
			f"New user signed up: {instance.email}",
			setting_key='new_user_signup',
		)

@receiver(post_save, sender=Notification)
def notification_creation_handler(sender, instance, created, **kwargs):
    if not created:
        return

    if created:
        channel_layer = get_channel_layer()
        group_name = f"user_{instance.user.id}"
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': 'send_notification',
                'data': {
                    'id': instance.id,
                    'message': instance.message,
                    'created_at': instance.created_at.isoformat(),
                }
            }
        )


@receiver(post_save, sender='main.AIInsight')
def ai_insight_creation_handler(sender, instance, created, **kwargs):
    """Notify org OWNER/ADMIN members when a new AI recommendation is created."""
    if not created:
        return
    from accounts.notifications import notify_org_members
    notify_org_members(
        instance.organization,
        f"New AI recommendation for campaign \"{instance.campaign.name}\": {instance.title}",
        setting_key='ai_recommendations',
    )
