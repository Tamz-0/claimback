from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Campus user. Roles are Django groups (see roles.py)."""

    class Affiliation(models.TextChoices):
        STUDENT = "student", "Student"
        STAFF = "staff", "Staff"

    affiliation = models.CharField(max_length=10, choices=Affiliation.choices, default=Affiliation.STUDENT)
    campus_id = models.CharField("Campus ID / roll no.", max_length=40, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.get_full_name() or self.username
