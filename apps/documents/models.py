"""Expediente documental (Fase 7).

Decisiones de modelo que conviene tener a la vista:

- **El nombre del archivo lo genera el sistema**, nunca el usuario: la ruta es
  `documents/<public_id del empleado>/<uuid4>.<extensión validada>`. Lo que la
  persona subió se guarda aparte, en `original_filename`, y solo se muestra
  escapado (§K.4).
- **`allowed_extensions` es una lista corta de configuración**, no una relación:
  se guarda como texto separado por comas y lo parsea el validador. No se usa
  `ArrayField` porque ata el proyecto a PostgreSQL (ADR-003) ni JSON, que sería
  esconder una relación en un campo (regla 7).
- **Los documentos no se borran: se archivan.** Un expediente es prueba, y una
  baja por error no debe destruirla. Por eso `delete_employeedocument` no se
  otorga nunca y existe `archive_document`.
- **`checksum_sha256` no es decoración**: detecta que el mismo archivo se subió
  dos veces y permite verificar la integridad años después.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models.functions import Length
from django.db.models.lookups import Exact
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.documents.constants import (
    ALLOWED_EXTENSIONS,
    CHECKSUM_LENGTH,
    MAX_RETENTION_YEARS,
    MAX_SIZE_MB,
)


def document_upload_path(
    instance: EmployeeDocument,
    filename: str,  # noqa: ARG001 - se ignora a propósito: lo envía el cliente
) -> str:
    """Ruta de almacenamiento. **No usa `filename`**: lo trae el cliente.

    Django pasa el nombre subido; se ignora a propósito y se arma uno nuevo con
    la extensión ya validada por el servicio. Así un nombre como
    `../../etc/passwd` no tiene por dónde entrar (§K.4).
    """
    extension = (instance.validated_extension or "bin").lower()
    return f"documents/{instance.employee.public_id}/{uuid.uuid4()}.{extension}"


class DocumentType(TimeStampedModel):
    """Catálogo: contrato firmado, constancia, expediente médico…"""

    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=80)
    is_sensitive = models.BooleanField(
        _("confidential"),
        default=False,
        help_text=_("Only HR administration and auditing can open its content."),
    )
    requires_expiry = models.BooleanField(
        _("requires expiry date"),
        default=False,
        help_text=_("For example, a medical certificate or a work permit."),
    )
    employee_can_upload = models.BooleanField(
        _("the employee can upload it"),
        default=False,
        help_text=_("Types a person may add to their own file, such as a diploma."),
    )
    retention_years = models.PositiveSmallIntegerField(
        _("retention (years)"),
        default=0,
        help_text=_("How long it must be kept. 0 means no policy defined yet."),
    )
    allowed_extensions = models.CharField(
        _("allowed formats"),
        max_length=100,
        default="pdf",
        help_text=_("Comma-separated list, for example: pdf,png,jpg"),
    )
    max_size_mb = models.PositiveSmallIntegerField(_("maximum size (MB)"), default=10)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("document type")
        verbose_name_plural = _("document types")
        ordering = ("code",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_size_mb__gt=0) & models.Q(max_size_mb__lte=MAX_SIZE_MB),
                name="document_type_size_in_range",
                violation_error_message=_("The maximum size must be between 1 and 25 MB."),
            ),
            models.CheckConstraint(
                condition=models.Q(retention_years__lte=MAX_RETENTION_YEARS),
                name="document_type_retention_in_range",
                violation_error_message=_("The retention cannot exceed 50 years."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def extensions(self) -> tuple[str, ...]:
        """Extensiones admitidas por este tipo, ya normalizadas.

        Se cruza con la allowlist global: lo que no esté ahí no existe, aunque
        alguien lo escriba en el catálogo.
        """
        declared = {
            part.strip().lower().lstrip(".")
            for part in self.allowed_extensions.split(",")
            if part.strip()
        }
        return tuple(sorted(declared & set(ALLOWED_EXTENSIONS)))


class EmployeeDocument(TimeStampedModel):
    """Un archivo del expediente de una persona."""

    public_id = models.UUIDField(
        _("public id"), default=uuid.uuid4, editable=False, unique=True, db_index=True
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("employee"),
    )
    document_type = models.ForeignKey(
        "documents.DocumentType",
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name=_("document type"),
    )
    title = models.CharField(_("title"), max_length=150)
    stored_path = models.FileField(_("stored file"), upload_to=document_upload_path, max_length=300)
    original_filename = models.CharField(_("original file name"), max_length=255)
    content_type = models.CharField(_("declared content type"), max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(_("size (bytes)"))
    checksum_sha256 = models.CharField(_("checksum (SHA-256)"), max_length=CHECKSUM_LENGTH)
    issued_on = models.DateField(_("issued on"), null=True, blank=True)
    expires_on = models.DateField(_("expires on"), null=True, blank=True)
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("uploaded by"),
    )
    is_active = models.BooleanField(_("active"), default=True)
    archived_reason = models.CharField(_("archiving reason"), max_length=300, blank=True)

    #: Extensión que el servicio ya validó. No es columna: solo viaja hasta que
    #: `document_upload_path` arma el nombre del archivo.
    validated_extension: str = ""

    class Meta:
        verbose_name = _("employee document")
        verbose_name_plural = _("employee documents")
        ordering = ("-created_at",)
        # Sin `delete`: un expediente no se borra, se archiva (§J.3).
        default_permissions = ("add", "change", "view")
        permissions = [
            ("view_sensitive_document", _("Can open confidential documents")),
            ("archive_document", _("Can archive a document")),
        ]
        constraints = [
            # El mismo archivo, para la misma persona y el mismo tipo, una vez.
            models.UniqueConstraint(
                fields=["employee", "document_type", "checksum_sha256"],
                condition=models.Q(is_active=True),
                name="uniq_active_document_per_checksum",
                violation_error_message=_("That same file is already in the file."),
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name="document_size_positive",
                violation_error_message=_("An empty file explains nothing."),
            ),
            models.CheckConstraint(
                condition=Exact(Length("checksum_sha256"), CHECKSUM_LENGTH),
                name="document_checksum_is_sha256",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_on__isnull=True)
                | models.Q(expires_on__isnull=True)
                | models.Q(issued_on__lte=models.F("expires_on")),
                name="document_dates_ordered",
                violation_error_message=_("The expiry cannot precede the issue date."),
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "document_type"], name="document_employee_type_idx"),
            models.Index(fields=["expires_on"], name="document_expires_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.document_type.code} {self.title}"

    @property
    def extension(self) -> str:
        return self.stored_path.name.rsplit(".", 1)[-1].lower() if self.stored_path else ""

    def days_to_expiry(self) -> int | None:
        if self.expires_on is None:
            return None
        return (self.expires_on - timezone.localdate()).days

    @property
    def is_expired(self) -> bool:
        days = self.days_to_expiry()
        return days is not None and days < 0
