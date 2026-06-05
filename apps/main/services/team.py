import random
from django.db import models
from django.conf import settings
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.response import Response
from apps.accounts.models import User
from apps.main.models import Organization, OrganizationMember, TeamInvitation
from apps.accounts.email_utils import send_team_invitation_email, send_account_created_email
from apps.accounts.notifications import notify_user, notify_org_members

class TeamService:
    def get_team_stats(self, organization):
        return OrganizationMember.objects.filter(organization=organization).aggregate(
            total_members=models.Count('id'),
            active_members=models.Count('id', filter=models.Q(user__is_active=True)),
            inactive_members=models.Count('id', filter=models.Q(user__is_active=False)),
            pending_invitations=models.Count('id', filter=models.Q(status='PENDING'))
        )

    def get_team_members_queryset(self, organization):
        return OrganizationMember.objects.filter(organization=organization).select_related('user')

    def update_team_member(self, instance, new_role, user_performing_update):
        if instance.role == 'OWNER':
            return Response({'error': 'Cannot modify the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
        
        old_role = instance.role
        instance.role = new_role
        instance.save()

        if instance.user and new_role != old_role:
            notify_user(
                instance.user,
                f"Your role in {instance.organization.name} has been updated to {new_role}.",
                organization=instance.organization,
                setting_key='team_activity',
            )
        return Response(status=status.HTTP_200_OK)

    def delete_team_member(self, instance):
        if instance.role == 'OWNER':
            return Response({'error': 'Cannot delete the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
        
        member_user = instance.user
        organization = instance.organization
        instance.delete()

        if member_user:
            notify_user(
                member_user,
                f"You have been removed from {organization.name}.",
                setting_key='team_activity',
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def invite_team_member(self, organization, email, role, invited_by):
        user = User.objects.filter(email=email).first()
        if user:
            if OrganizationMember.objects.filter(user=user, organization=organization).exists():
                raise ValidationError({'error': 'User is already a member of the organization.'})
            if user.is_staff or user.is_superuser:
                raise ValidationError({'error': 'Cannot invite admin or superuser as organization member.'})
        
        invitation = TeamInvitation.objects.create(
            email=email,
            role=role,
            organization=organization,
            invited_by=invited_by
        )
        invite_link = f"{settings.FRONTEND_URL}/accept-invite/{invitation.token}/"
        
        try:
            send_team_invitation_email(
                invitee_email=email,
                inviter_name=invited_by.full_name or invited_by.email,
                organization_name=organization.name,
                invite_link=invite_link
            )
        except Exception:
            pass

        if user:
            notify_user(
                user,
                f"You have been invited to join {organization.name} as {role} by {invited_by.full_name or invited_by.email}.",
                organization=organization,
                setting_key='team_activity',
            )
        
        notify_org_members(
            organization,
            f"{email} has been invited to join the organization as {role}.",
            setting_key='team_activity',
        )
        return invitation

    def accept_invitation(self, token):
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            invitation = TeamInvitation.objects.filter(token=token, status='PENDING').first()
        except (DjangoValidationError, ValueError):
            raise ValidationError({'error': 'Invalid or expired invitation token.'})

        if not invitation:
            raise ValidationError({'error': 'Invalid or expired invitation token.'})
        
        user = User.objects.filter(email=invitation.email).first()
        if not user:
            temp_password = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
            user = User.objects.create_user(
                email=invitation.email,
                password=temp_password,
                is_active=True
            )
            try:
                send_account_created_email(
                    user_email=invitation.email,
                    temp_password=temp_password,
                    organization_name=invitation.organization.name
                )
            except Exception:
                pass

        if OrganizationMember.objects.filter(user=user, organization=invitation.organization).exists():
            raise ValidationError({'error': 'You are already a member of this organization.'})
        
        OrganizationMember.objects.create(
            user=user,
            organization=invitation.organization,
            role=invitation.role,
            status='ACTIVE'
        )
        invitation.status = 'ACCEPTED'
        invitation.save()

        notify_org_members(
            invitation.organization,
            f"{user.email} has joined the organization as {invitation.role}.",
            setting_key='team_activity',
        )
        if invitation.invited_by and invitation.invited_by != user:
            notify_user(
                invitation.invited_by,
                f"{user.email} accepted your invitation to join {invitation.organization.name}.",
                organization=invitation.organization,
                setting_key='team_activity',
            )
        return invitation.organization, invitation.role
