"""
Test script to preview email templates.
Run this to generate preview HTML files with sample data.
"""
import os
from datetime import datetime

# Sample context data for each template
templates = {
    'email_otp_verification.html': {
        'context': {
            'user_name': 'John Doe',
            'otp': '123456',
            'expiry_minutes': '10',
            'year': datetime.now().year
        },
        'output': 'preview_otp.html'
    },
    'email_team_invitation.html': {
        'context': {
            'inviter_name': 'Jane Smith',
            'organization_name': 'Acme Corp',
            'invite_link': 'https://adportal.com/accept-invite/abc123',
            'year': datetime.now().year
        },
        'output': 'preview_invitation.html'
    },
    'email_welcome.html': {
        'context': {
            'user_name': 'John Doe',
            'dashboard_link': 'https://adportal.com/dashboard',
            'support_email': 'support@adportal.com',
            'year': datetime.now().year
        },
        'output': 'preview_welcome.html'
    },
    'email_account_created.html': {
        'context': {
            'user_email': 'john.doe@example.com',
            'temp_password': 'abc123xyz789',
            'organization_name': 'Acme Corp',
            'login_link': 'https://adportal.com/login',
            'year': datetime.now().year
        },
        'output': 'preview_account_created.html'
    }
}

def render_template(template_content, context):
    """Replace template variables with sample data."""
    for key, value in context.items():
        placeholder = f"{{{{{key}}}}}"
        template_content = template_content.replace(placeholder, str(value))
    return template_content

def generate_previews():
    """Generate preview HTML files for all email templates."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    for template_name, config in templates.items():
        template_path = os.path.join(base_dir, template_name)
        output_path = os.path.join(base_dir, config['output'])
        
        try:
            # Read template
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Render with sample data
            rendered = render_template(template_content, config['context'])
            
            # Write preview
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(rendered)
            
            print(f"✓ Generated {config['output']}")
        
        except FileNotFoundError:
            print(f"✗ Template not found: {template_name}")
        except Exception as e:
            print(f"✗ Error processing {template_name}: {str(e)}")

if __name__ == '__main__':
    print("Generating email template previews...")
    print("-" * 50)
    generate_previews()
    print("-" * 50)
    print("\nPreview files created! Open them in a browser to see how emails will look.")
    print("\nUsage in Django:")
    print("  from accounts.email_utils import send_otp_email, send_team_invitation_email")
    print("  from accounts.email_utils import send_welcome_email, send_account_created_email")
