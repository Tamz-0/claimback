from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Notification


@login_required
def notifications(request):
    items = request.user.notifications.all()[:100]
    response = render(request, "audit/notifications.html", {"notifications": items})
    request.user.notifications.filter(read=False).update(read=True)
    return response


@login_required
def open_notification(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.read = True
    n.save(update_fields=["read"])
    return redirect(n.url or "audit:notifications")
