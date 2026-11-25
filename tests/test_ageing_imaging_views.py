"""Ageing/disposal, EXIF stripping, role permissions and page smoke tests."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from PIL import Image

from apps.custody import services as custody
from apps.custody.models import CustodyRecord
from apps.items.models import Item, ItemPhoto

from .conftest import make_user


@pytest.mark.django_db
class TestAgeing:
    """ACCEPTANCE: unclaimed items age into the disposal queue at the configured interval."""

    def test_item_ages_then_enters_disposal_queue(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        retention = found_item.category.retention_days      # Phone = 60 days
        start = found_item.custody_started_at()

        assert custody.age_items(now=start + timedelta(days=retention - 8)) == {"warned": 0, "queued": 0}
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.IN_CUSTODY

        assert custody.age_items(now=start + timedelta(days=retention - 7))["warned"] == 1
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.AGEING
        assert users["guard"].notifications.filter(kind="ageing_warning").exists()

        assert custody.age_items(now=start + timedelta(days=retention))["queued"] == 1
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.DISPOSAL_QUEUE

    def test_retention_is_configurable_per_category(self, found_item, users, ref):
        found_item.category.retention_days = 10
        found_item.category.save()
        custody.record_intake(found_item, users["guard"], ref["desk"])
        custody.age_items(now=timezone.now() + timedelta(days=10, minutes=1))
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.DISPOSAL_QUEUE

    def test_item_with_open_claim_does_not_age(self, found_item, users, ref):
        from apps.claims.services import submit_claim

        custody.record_intake(found_item, users["guard"], ref["desk"])
        submit_claim(item=found_item, claimant=users["owner"])
        custody.age_items(now=timezone.now() + timedelta(days=365))
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.CLAIM_PENDING

    def test_disposal_recorded_in_custody_chain(self, found_item, users, ref):
        custody.record_intake(found_item, users["guard"], ref["desk"])
        with pytest.raises(ValidationError):
            custody.dispose(found_item, users["guard"], "donated")      # not in queue yet
        custody.age_items(now=timezone.now() + timedelta(days=400))
        custody.dispose(found_item, users["guard"], "donated", recipient="NGO")
        found_item.refresh_from_db()
        assert found_item.status == Item.Status.DISPOSED
        assert found_item.custody_records.last().action == CustodyRecord.Action.DISPOSAL
        assert found_item.disposal.recipient == "NGO"


@pytest.mark.django_db
def test_exif_and_gps_are_stripped_before_storage(found_item, make_image):
    upload = make_image(with_gps=True)
    with Image.open(upload) as original:
        assert original.getexif().get(0x8825) is not None    # the test image really has GPS
    upload.seek(0)
    photo = ItemPhoto.create_from_upload(found_item, upload)
    for f in (photo.image, photo.thumbnail):
        with Image.open(f.path) as stored:
            exif = stored.getexif()
            assert len(exif) == 0, dict(exif)
            assert "exif" not in stored.info
    with open(photo.image.path, "rb") as fh:
        raw = fh.read()
    assert b"SecretPhone" not in raw and b"PhoneMaker" not in raw


@pytest.mark.django_db
def test_invalid_image_rejected(found_item):
    from django.core.files.uploadedfile import SimpleUploadedFile

    with pytest.raises(ValidationError):
        ItemPhoto.create_from_upload(found_item, SimpleUploadedFile("x.jpg", b"not an image"))


@pytest.mark.django_db
def test_found_report_requires_hidden_details(ref, users):
    from apps.items.services import create_report

    with pytest.raises(ValidationError):
        create_report(reporter=users["finder"], kind="found", title="Keys", description="", category=ref["phone"],
                      location=ref["room"], occurred_at=timezone.now(), private_pairs=[("q", "a")])


@pytest.mark.django_db
def test_report_form_end_to_end_with_photo(ref, users, make_image):
    c = Client()
    c.force_login(users["finder"])
    resp = c.post("/items/report/found/", {
        "title": "Blue umbrella", "category": ref["phone"].pk, "location": ref["room"].pk,
        "occurred_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "description": "",
        "pq_1": "Handle colour?", "pa_1": "wooden", "pq_2": "Any tag?", "pa_2": "initials KR",
        "photos": [make_image(with_gps=True)],
    })
    assert resp.status_code == 302, resp.content.decode()[:2000]
    item = Item.objects.get(title="Blue umbrella")
    assert item.photos.count() == 1


@pytest.mark.django_db
class TestPagesAndRoles:
    def test_pages_render_for_each_role(self, found_item, users, ref):
        from apps.dashboard import seeding

        campus_admin = make_user("cadmin")
        from django.contrib.auth.models import Group

        campus_admin.groups.add(Group.objects.get(name="Campus Admin"))
        anon = Client()
        for url in ("/", f"/item/{found_item.pk}/", "/accounts/login/", "/accounts/signup/"):
            assert anon.get(url).status_code == 200, url
        assert anon.get("/items/report/lost/").status_code == 302   # login required

        student = Client()
        student.force_login(users["owner"])
        for url in ("/items/report/lost/", "/items/report/found/", "/me/", f"/claims/item/{found_item.pk}/", "/notifications/"):
            assert student.get(url).status_code == 200, url
        for url in ("/desk/", "/desk/matches/", "/reports/", "/desk/audit/"):
            assert student.get(url).status_code == 403, url

        guard = Client()
        guard.force_login(users["guard"])
        for url in ("/desk/", f"/desk/item/{found_item.pk}/", "/desk/matches/", "/desk/audit/", "/reports/",
                    "/reports/?format=csv", f"/items/{found_item.pk}/"):
            assert guard.get(url).status_code == 200, url

        admin_c = Client()
        admin_c.force_login(campus_admin)
        assert admin_c.get("/reports/").status_code == 200
        assert admin_c.get("/desk/").status_code == 403    # campus admin is not security

    def test_claim_via_web_flow(self, found_item, users):
        c = Client()
        c.force_login(users["owner"])
        resp = c.post(f"/claims/item/{found_item.pk}/", {"statement": "Mine"})
        assert resp.status_code == 302
        claim = found_item.claims.get()
        page = c.get(f"/claims/{claim.pk}/").content.decode()
        assert "Prove it" in page
