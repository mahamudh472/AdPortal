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
