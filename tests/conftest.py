import io
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.accounts.roles import SECURITY
from apps.catalog.models import Category, Location
from apps.dashboard import seeding
from apps.items.models import Item
from apps.items.services import create_report


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def ref(db):
    seeding.seed_reference_data()
    return {
        "phone": Category.objects.get(name="Phone"),
        "wallet": Category.objects.get(name="Wallet & Purse"),
        "room": Location.objects.get(name="Room A-204"),
        "desk": Location.objects.get(name="Security Office"),
        "library_desk": Location.objects.get(name="Library Security Desk"),
    }


def make_user(username, security=False, **extra):
    u = User.objects.create_user(username=username, password="pw-12345678", email=f"{username}@x.test", **extra)
    if security:
        u.groups.add(Group.objects.get_or_create(name=SECURITY)[0])
    return u


@pytest.fixture
def users(ref):
    return {
        "finder": make_user("finder"),
        "owner": make_user("owner"),
        "other": make_user("other"),
        "guard": make_user("guard", security=True),
    }


CANARY_Q = "CANARYQ7f3a What colour is the hidden sticker"
CANARY_A = "CANARYA9b1c zebra striped hidden sticker"
CANARY_Q2 = "CANARYQ2e4d Lock screen picture"
CANARY_A2 = "CANARYA5c6e grandmother in red saree"
CANARIES = ["CANARYQ7f3a", "CANARYA9b1c", "CANARYQ2e4d", "CANARYA5c6e", "zebra striped", "grandmother in red saree"]


@pytest.fixture
def found_item(ref, users):
    return create_report(
        reporter=users["finder"], kind=Item.Kind.FOUND, title="Black Apple iPhone",
        description="Phone left on a desk", category=ref["phone"], location=ref["room"],
        occurred_at=timezone.now() - timedelta(hours=2), attributes={"colour": "black", "brand": "Apple"},
        private_pairs=[(CANARY_Q, CANARY_A), (CANARY_Q2, CANARY_A2), ("Case?", "clear case with dried flower")],
    )


def image_file(name="photo.jpg", with_gps=False, size=(800, 600)):
    img = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if with_gps:
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"          # Make
        exif[0x0110] = "SecretPhone 9"       # Model
        gps = {1: "N", 2: (28.0, 36.0, 50.0), 3: "E", 4: (77.0, 12.0, 30.0)}
        exif[0x8825] = gps                   # GPSInfo IFD
        img.save(buf, format="JPEG", exif=exif.tobytes())
    else:
        img.save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@pytest.fixture
def make_image():
    return image_file
