from .roles import is_campus_admin, is_security


def roles(request):
    user = getattr(request, "user", None)
    ctx = {"is_security": False, "is_campus_admin": False, "unread_notifications": 0}
    if user and user.is_authenticated:
        ctx["is_security"] = is_security(user)
        ctx["is_campus_admin"] = is_campus_admin(user)
        ctx["unread_notifications"] = user.notifications.filter(read=False).count()
    return ctx
