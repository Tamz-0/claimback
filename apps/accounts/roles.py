"""
Roles from the spec, implemented as Django groups.

Student / Staff        -> any logged-in user (no group needed)
Security Personnel     -> group "Security"
Campus Administrator   -> group "Campus Admin"
System Administrator   -> group "System Admin" (or Django superuser)
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

SECURITY = "Security"
CAMPUS_ADMIN = "Campus Admin"
SYSTEM_ADMIN = "System Admin"
ALL_ROLE_GROUPS = [SECURITY, CAMPUS_ADMIN, SYSTEM_ADMIN]


def has_role(user, group_name):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=group_name).exists()


def is_security(user):
    return has_role(user, SECURITY)


def is_campus_admin(user):
    return has_role(user, CAMPUS_ADMIN) or has_role(user, SYSTEM_ADMIN)


def is_staff_role(user):
    """Any back-office role (security, campus admin, system admin)."""
    return is_security(user) or is_campus_admin(user)


def role_required(check):
    """View decorator: `@role_required(is_security)`."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied("You do not have the role required for this page.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
