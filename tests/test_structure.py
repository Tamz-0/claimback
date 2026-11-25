"""Structural guarantees that make private-detail leaks hard to introduce by accident."""

import ast
from pathlib import Path

import pytest
from django.db import connection

from apps.board.public import PUBLIC_FIELDS, to_public
from apps.items.models import Item
from apps.vault.models import PrivateDetail

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_MODULES = ["apps/board/public.py", "apps/board/views.py", "apps/board/search.py", "apps/board/urls.py"]


@pytest.mark.parametrize("path", PUBLIC_MODULES)
def test_public_modules_do_not_import_the_vault(path):
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "vault" not in (node.module or ""), f"{path} imports {node.module}"
        if isinstance(node, ast.Import):
            assert not any("vault" in a.name for a in node.names), path


def test_item_has_no_relation_to_private_details():
    names = {f.name for f in Item._meta.get_fields()}
    assert not any("private" in n for n in names), names
    for f in Item._meta.get_fields():
        assert getattr(f, "related_model", None) is not PrivateDetail


@pytest.mark.django_db
def test_default_manager_is_locked(found_item):
    assert PrivateDetail.objects.count() == 0               # locked manager returns nothing
    assert PrivateDetail.vault.filter(item=found_item).count() == 3


@pytest.mark.django_db
def test_private_details_encrypted_at_rest(found_item):
    with connection.cursor() as cur:
        cur.execute("SELECT question, answer FROM vault_privatedetail")
        rows = cur.fetchall()
    assert rows
    for q, a in rows:
        assert "CANARY" not in q and "CANARY" not in a and "dried flower" not in a
        assert q.startswith("gAAAA") and a.startswith("gAAAA")   # Fernet tokens


@pytest.mark.django_db
def test_public_dto_is_exactly_the_allow_list(found_item):
    assert tuple(to_public(found_item)) == PUBLIC_FIELDS
    assert set(PUBLIC_FIELDS) == {"id", "kind", "title", "description", "category", "category_icon", "attributes",
                                  "location", "date", "status", "claimable", "photo", "thumbnail"}


def test_private_detail_not_in_admin():
    from django.contrib import admin

    assert PrivateDetail not in admin.site._registry
