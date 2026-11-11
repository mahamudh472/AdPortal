from .models import AdminAuditLog


def record(request, action, target_type='', target_id='', **detail):
    """Write an audit entry for a staff action. Never raises into the request."""
    try:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        ip = (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None
        AdminAuditLog.objects.create(
            actor=request.user, actor_email=request.user.email, action=action,
            target_type=target_type, target_id=str(target_id), detail=detail, ip_address=ip,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to write audit log for %s", action)
