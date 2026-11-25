"""Field-level encryption for private identifying details (Fernet / AES-128-CBC + HMAC)."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


@lru_cache(maxsize=1)
def _fernet():
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        # Development fallback: derive a stable key from SECRET_KEY.
        key = base64.urlsafe_b64encode(hashlib.sha256(("vault:" + settings.SECRET_KEY).encode()).digest())
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Cannot decrypt private detail – wrong FIELD_ENCRYPTION_KEY?") from exc


class EncryptedTextField(models.TextField):
    """Stores ciphertext in the database; Python code sees plaintext."""

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return encrypt(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return decrypt(value)

    def to_python(self, value):
        return value
