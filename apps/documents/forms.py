"""Formularios del expediente documental.

Campos explícitos, nunca `__all__`. Ninguno expone al empleado: la ficha sale de
la URL validada por el selector (§J.4). El archivo **no** se valida aquí sino en
la cadena de §K.4, dentro del servicio: la validación de seguridad no puede
depender de qué formulario se use.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.documents.models import DocumentType, EmployeeDocument
from apps.documents.selectors import uploadable_types_for

_DATE = {"type": "date"}


class DocumentUploadForm(forms.ModelForm):
    """Subida de un documento. El tipo se elige primero: fija formatos y tamaño."""

    class Meta:
        model = EmployeeDocument
        fields = ["document_type", "title", "issued_on", "expires_on"]
        widgets = {
            "issued_on": forms.DateInput(attrs=_DATE),
            "expires_on": forms.DateInput(attrs=_DATE),
        }

    file = forms.FileField(label=_("File"))

    def __init__(self, *args, user=None, employee=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["document_type"]
        field.queryset = (
            uploadable_types_for(user, employee)
            if user is not None and employee is not None
            else DocumentType.objects.none()
        )
        field.empty_label = None
        self.fields["title"].required = False
        self.fields["title"].help_text = _("Optional: the file name is used if left empty.")

    def clean(self) -> dict:
        cleaned = super().clean()
        issued, expires = cleaned.get("issued_on"), cleaned.get("expires_on")
        if issued and expires and expires < issued:
            raise forms.ValidationError(
                _("The expiry cannot precede the issue date."), code="dates_unordered"
            )
        document_type = cleaned.get("document_type")
        if document_type is not None and document_type.requires_expiry and not expires:
            self.add_error("expires_on", _("This document type requires an expiry date."))
        return cleaned


class ArchiveDocumentForm(forms.Form):
    """Archivar exige motivo: alguien lo va a leer dentro de dos años."""

    reason = forms.CharField(
        label=_("Reason"),
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("It is recorded in the audit log with your name."),
    )


class DocumentTypeForm(forms.ModelForm):
    """Catálogo de tipos de documento."""

    class Meta:
        model = DocumentType
        fields = [
            "code",
            "name",
            "is_sensitive",
            "requires_expiry",
            "employee_can_upload",
            "retention_years",
            "allowed_extensions",
            "max_size_mb",
            "is_active",
        ]

    def clean_allowed_extensions(self) -> str:
        """Solo formatos de la allowlist global: lo demás no se guarda."""
        from apps.documents.constants import ALLOWED_EXTENSIONS

        declared = [
            part.strip().lower().lstrip(".")
            for part in self.cleaned_data["allowed_extensions"].split(",")
            if part.strip()
        ]
        unknown = sorted(set(declared) - set(ALLOWED_EXTENSIONS))
        if unknown:
            raise forms.ValidationError(
                _("These formats are not accepted: %(unknown)s"),
                code="extension_not_allowed",
                params={"unknown": ", ".join(unknown)},
            )
        if not declared:
            raise forms.ValidationError(
                _("A document type needs at least one format."), code="type_without_formats"
            )
        return ",".join(dict.fromkeys(declared))
