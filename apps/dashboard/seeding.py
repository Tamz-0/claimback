"""Functions that load demo_data into the database. Used by `seed_demo` and by the tests."""

from datetime import timedelta

from django.contrib.auth.models import Group
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ALL_ROLE_GROUPS
from apps.catalog.models import Category, Location
from apps.items.models import Item
from apps.items.services import create_report

from . import demo_data as D


def seed_reference_data():
    for name, icon, attrs, prompts, retention in D.CATEGORIES:
        Category.objects.update_or_create(
            name=name, defaults={"icon": icon, "attributes": attrs, "verification_prompts": prompts, "retention_days": retention}
        )
    campus, _ = Location.objects.get_or_create(name="Main Campus", parent=None, defaults={"kind": Location.Kind.CAMPUS})
    for building, x, y, areas, custody_area in D.CAMPUS:
        b, _ = Location.objects.update_or_create(
            name=building, parent=campus, defaults={"kind": Location.Kind.BUILDING, "map_x": x, "map_y": y}
        )
        for area in areas:
            Location.objects.update_or_create(
                name=area, parent=b, defaults={"kind": Location.Kind.AREA, "is_custody_point": area == custody_area}
            )
    for g in ALL_ROLE_GROUPS:
        Group.objects.get_or_create(name=g)


def seed_users(password=D.DEMO_PASSWORD):
    users = {}
    for username, first, last, aff, groups in D.USERS:
        u, created = User.objects.get_or_create(
            username=username,
            defaults={"first_name": first, "last_name": last, "affiliation": aff, "email": f"{username}@campus.local"},
        )
        if created:
            u.set_password(password)
            u.save()
        for g in groups:
            u.groups.add(Group.objects.get(name=g))
        if username == "sysadmin":
            u.is_staff = u.is_superuser = True
            u.save()
        if username == "campusadmin":
            u.is_staff = True
            u.save()
            from django.contrib.auth.models import Permission

            perms = Permission.objects.filter(content_type__app_label="catalog")
            u.user_permissions.add(*perms)
        users[username] = u
    return users


def loc(building, area):
    return Location.objects.get(name=area, parent__name=building)


def seed_match_pairs(lost_by, found_by, base_time=None, pairs=None):
    """Create lost/found reports for every MATCH_PAIR. Returns [(lost_item, found_item)]."""
    base_time = base_time or timezone.now() - timedelta(days=5)
    created = []
    for i, p in enumerate(pairs or D.MATCH_PAIRS):
        cat = Category.objects.get(name=p["cat"])
        t_lost = base_time + timedelta(hours=i * 3)
        lt, ld, la, (lb, lar) = p["lost"]
        ft, fd, fa, (fb, far) = p["found"]
        lost = create_report(reporter=lost_by, kind=Item.Kind.LOST, title=lt, description=ld, category=cat,
                             location=loc(lb, lar), occurred_at=t_lost, attributes=la)
        found = create_report(reporter=found_by, kind=Item.Kind.FOUND, title=ft, description=fd, category=cat,
                              location=loc(fb, far), occurred_at=t_lost + timedelta(hours=p["hours"]), attributes=fa,
                              private_pairs=p["private"], photo_public=False)
        created.append((lost, found))
    return created


def seed_distractors(found_by, base_time=None):
    base_time = base_time or timezone.now() - timedelta(days=4)
    out = []
    for i, (title, cat, desc, attrs, (b, a)) in enumerate(D.DISTRACTORS):
        out.append(create_report(
            reporter=found_by, kind=Item.Kind.FOUND, title=title, description=desc,
            category=Category.objects.get(name=cat), location=loc(b, a), occurred_at=base_time + timedelta(hours=i),
            attributes=attrs, private_pairs=[("Hidden mark", f"mark {i}"), ("Colour detail", f"detail {i}")],
        ))
    return out
