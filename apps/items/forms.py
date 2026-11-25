from django import forms
from django.utils import timezone

from apps.catalog.models import Category, Location

MAX_PHOTOS = 4
MAX_PRIVATE = 5


class ReportForm(forms.Form):
    """Single-screen report form, designed to be completed in under 60 seconds on a phone."""

    title = forms.CharField(max_length=120, widget=forms.TextInput(attrs={
        "placeholder": "e.g. Black HP laptop bag", "autocomplete": "off"}))
    category = forms.ModelChoiceField(queryset=Category.objects.filter(is_active=True), empty_label="Choose…")
    location = forms.ModelChoiceField(queryset=Location.objects.filter(is_active=True), empty_label="Choose on map or list…")
    occurred_at = forms.DateTimeField(
        label="When", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={
        "rows": 2, "placeholder": "Public description (no identifying details!)"}))
    photo_public = forms.BooleanField(required=False, initial=True, label="Show photo on the public board")

    def __init__(self, *args, kind="lost", **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        self.fields["occurred_at"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        if kind == "found":
            self.fields["photo_public"].initial = False
            self.fields["photo_public"].help_text = "Leave off if the photo shows identifying marks."

    def clean_occurred_at(self):
        value = self.cleaned_data["occurred_at"]
        if value > timezone.now() + timezone.timedelta(minutes=10):
            raise forms.ValidationError("That time is in the future.")
        return value

    def attributes_from(self, data):
        cat = self.cleaned_data.get("category")
        if not cat:
            return {}
        return {key: data.get(f"attr_{key}", "")[:60] for key in cat.attributes}

    @staticmethod
    def private_pairs_from(data):
        return [(data.get(f"pq_{i}", ""), data.get(f"pa_{i}", "")) for i in range(1, MAX_PRIVATE + 1)]

    @staticmethod
    def photos_from(files):
        photos = files.getlist("photos")[:MAX_PHOTOS]
        return [p for p in photos if p and p.size]
