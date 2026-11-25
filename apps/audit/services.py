import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import AuditEntry, Notification

log = logging.getLogger(__name__)


def audit(actor, action, target, **data):
    """Record an audit entry. `target` is any model instance."""
    return AuditEntry.objects.create(
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        action=action,
        target_type=target.__class__.__name__,
        target_id=str(target.pk),
        data=data,
    )


def notify(user, kind, message, url="", email=True):
    """In-app notification plus email. SMS is a stub (see send_sms)."""
    n = Notification.objects.create(user=user, kind=kind, message=message[:300], url=url)
    if email and user.email:
        try:
            send_mail(
                subject=f"[Campus Lost & Found] {Notification.Kind(kind).label}",
                message=f"{message}\n\n{url}" if url else message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:  # pragma: no cover - email must never break the workflow
            log.exception("Email notification failed")
    return n


def send_sms(phone, text):
    """Integration point for an SMS gateway. Logs only in v1."""
    log.info("SMS to %s: %s", phone, text)
