from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import User
from main.models import Organization, OrganizationMember, OrganizationRole

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
