"""
Image sanitising.

A phone photo can carry the exact GPS coordinates of whoever took it (EXIF
metadata). We therefore strip ALL metadata *before* anything is stored: the
upload is decoded, rotated upright, resized, and re-encoded from raw pixels
into a brand-new JPEG that has no EXIF/XMP/ICC blocks at all.
"""

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1600
THUMB_SIDE = 400
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 60_000_000  # guard against decompression bombs


def _clean_copy(img: Image.Image, max_side: int) -> bytes:
    img = ImageOps.exif_transpose(img)  # honour orientation, then drop the tag
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    # Copy pixel data into a fresh image so no metadata (img.info) survives.
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=85, optimize=True)  # no exif= argument -> no EXIF
    return out.getvalue()


def sanitize_image(uploaded_file):
    """Return (full_image, thumbnail) as ContentFiles with all metadata removed."""
    if uploaded_file.size and uploaded_file.size > MAX_UPLOAD_BYTES:
        raise ValidationError("Photo is too large (max 12 MB).")
    try:
        img = Image.open(uploaded_file)
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("That file is not a valid image.") from exc
    name = uuid.uuid4().hex
    full = ContentFile(_clean_copy(img, MAX_SIDE), name=f"{name}.jpg")
    thumb = ContentFile(_clean_copy(img, THUMB_SIDE), name=f"{name}_t.jpg")
    return full, thumb
