"""
Email utility functions for sending HTML emails using templates.
"""
import os
from datetime import datetime
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def get_user_display_name(user_or_email, fallback_name=None):
    """
    Get display name from user object or email string.
    
    Args:
        user_or_email: User object or email string
        fallback_name: Optional fallback name
    
    Returns:
        Display name string
    """
    # If it's a User object with get_full_name method
    if hasattr(user_or_email, 'get_full_name'):
        return user_or_email.get_full_name()
    
    # If it's a User object with first_name/last_name
    if hasattr(user_or_email, 'first_name') and hasattr(user_or_email, 'last_name'):
        if user_or_email.first_name and user_or_email.last_name:
            return f"{user_or_email.first_name} {user_or_email.last_name}".strip()
        elif user_or_email.first_name:
            return user_or_email.first_name
        elif user_or_email.last_name:
            return user_or_email.last_name
    
    # If it's a string (email)
    if isinstance(user_or_email, str):
        if '@' in user_or_email:
            return user_or_email.split('@')[0]
        return user_or_email
    
    # Fallback
    return fallback_name or 'User'


def load_email_template(template_name):
    """
    Load an HTML email template from the project root.
    
    Args:
        template_name: Name of the template file (e.g., 'email_otp_verification.html')
    
    Returns:
        Template content as string
    """
    template_path = os.path.join(settings.BASE_DIR, template_name)
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Email template not found: {template_path}")


def render_template(template_content, context):
    """
    Render an email template by replacing placeholder variables.
    
    Args:
        template_content: HTML template string
        context: Dictionary of variables to replace
    
    Returns:
        Rendered HTML string
    """
    for key, value in context.items():
        placeholder = f"{{{{{key}}}}}"
        template_content = template_content.replace(placeholder, str(value))
    return template_content


def send_html_email(subject, to_email, template_name, context, from_email=None):
    """
    Send an HTML email using a template.
    
    Args:
        subject: Email subject line
        to_email: Recipient email address (string or list)
        template_name: Name of the HTML template file
        context: Dictionary of template variables
        from_email: Sender email (defaults to DEFAULT_FROM_EMAIL)
    
    Returns:
        Number of successfully sent emails
    """
    # Ensure to_email is a list
    if isinstance(to_email, str):
        to_email = [to_email]
    
    # Set default from_email
    if from_email is None:
        from_email = settings.DEFAULT_FROM_EMAIL
    
    # Add year to context if not present
    if 'year' not in context:
        context['year'] = datetime.now().year
    
    # Load and render template
    template_content = load_email_template(template_name)
    html_content = render_template(template_content, context)
    
    # Create plain text fallback from context (for email clients that don't support HTML)
    text_content = f"{subject}\n\n"
    for key, value in context.items():
        if key not in ['year', 'dashboard_link', 'invite_link', 'support_email']:
            text_content += f"{key.replace('_', ' ').title()}: {value}\n"
    
    # Create email message
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=to_email
    )
    
    # Attach HTML content
    email.attach_alternative(html_content, "text/html")
    
    # Send email
    return email.send()


def send_otp_email(user_email, user_name, otp_code, expiry_minutes=10):
    """
    Send OTP verification email.
    
    Args:
        user_email: Recipient email address
        user_name: User's name
        otp_code: 6-digit OTP code
        expiry_minutes: OTP expiry time in minutes
    
    Returns:
        Number of successfully sent emails
    """
    context = {
        'user_name': user_name or user_email.split('@')[0],
        'otp': otp_code,
        'expiry_minutes': expiry_minutes,
    }
    
    return send_html_email(
        subject='Your One-Time Password (OTP) - AdPortal',
        to_email=user_email,
        template_name='email_otp_verification.html',
        context=context
    )


def send_team_invitation_email(invitee_email, inviter_name, organization_name, invite_link):
    """
    Send team invitation email.
    
    Args:
        invitee_email: Recipient email address
        inviter_name: Name of person sending invitation
        organization_name: Name of the organization
        invite_link: URL to accept invitation
    
    Returns:
        Number of successfully sent emails
    """
    context = {
        'inviter_name': inviter_name,
        'organization_name': organization_name,
        'invite_link': invite_link,
    }
    
    return send_html_email(
        subject=f'You\'ve been invited to {organization_name} on AdPortal',
        to_email=invitee_email,
        template_name='email_team_invitation.html',
        context=context
    )


def send_welcome_email(user_email, user_name, dashboard_link=None, support_email=None):
    """
    Send welcome email after account creation.
    
    Args:
        user_email: Recipient email address
        user_name: User's name
        dashboard_link: URL to dashboard (optional)
        support_email: Support contact email (optional)
    
    Returns:
        Number of successfully sent emails
    """
    if dashboard_link is None:
        dashboard_link = f"{settings.FRONTEND_URL}/dashboard"
    
    if support_email is None:
        support_email = settings.DEFAULT_FROM_EMAIL
    
    context = {
        'user_name': user_name or user_email.split('@')[0],
        'dashboard_link': dashboard_link,
        'support_email': support_email,
    }
    
    return send_html_email(
        subject='Welcome to AdPortal! 🎉',
        to_email=user_email,
        template_name='email_welcome.html',
        context=context
    )


def send_account_created_email(user_email, temp_password, organization_name, login_link=None):
    """
    Send account creation email with temporary password.
    
    Args:
        user_email: Recipient email address
        temp_password: Temporary password for first login
        organization_name: Name of the organization they're joining
        login_link: URL to login page (optional)
    
    Returns:
        Number of successfully sent emails
    """
    if login_link is None:
        login_link = f"{settings.FRONTEND_URL}/login"
    
    context = {
        'user_email': user_email,
        'temp_password': temp_password,
        'organization_name': organization_name,
        'login_link': login_link,
    }
    
    return send_html_email(
        subject='Your Account Has Been Created - AdPortal',
        to_email=user_email,
        template_name='email_account_created.html',
        context=context
    )
