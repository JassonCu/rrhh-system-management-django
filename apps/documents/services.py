"""Casos de uso del expediente documental (Fase 7).

Invariantes que viven aquí porque la base no puede expresarlas:

- **RN-60**: el archivo se acepta solo si pasa la cadena completa de §K.4.
- **RN-61**: el nombre de almacenamiento lo genera el sistema; el del usuario se
  guarda aparte y solo para mostrarlo.
- **RN-62**: un documento no se borra, se **archiva** con motivo y queda auditado.
- **RN-63**: cada descarga se registra **antes** de entregar el archivo.
"""

from __future__ import annotations

import datetime as dt

from django.db import IntegrityError, transaction
from django.http import HttpRequest

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.core.exceptions import ConflictError
from apps.documents.models import DocumentType, EmployeeDocument
from apps.documents.validators import check_upload


@transaction.atomic
def upload_document(
    *,
    employee,
    document_type: DocumentType,
    upload,
    title: str,
    issued_on: dt.date | None,
    expires_on: dt.date | None,
    actor,
    request: HttpRequest | None,
) -> EmployeeDocument:
    """Valida y guarda un documento del expediente."""
    if not document_type.is_active:
        raise ConflictError("document_type_inactive", document_type=document_type.code)
    if document_type.requires_expiry and expires_on is None:
        raise ConflictError("expiry_required")
    if expires_on and issued_on and expires_on < issued_on:
        raise ConflictError("dates_unordered")

    checked = check_upload(upload, document_type)

    # El mismo archivo, en la misma ficha y el mismo tipo, una sola vez. El
    # índice único lo impone igual; esto explica el porqué antes de escribir.
    if EmployeeDocument.objects.filter(
        employee=employee,
        document_type=document_type,
        checksum_sha256=checked.checksum,
        is_active=True,
    ).exists():
        raise ConflictError("duplicate_document")

    document = EmployeeDocument(
        employee=employee,
        document_type=document_type,
        title=(title or checked.original_filename)[:150],
        original_filename=checked.original_filename,
        content_type=checked.content_type,
        size_bytes=checked.size_bytes,
        checksum_sha256=checked.checksum,
        issued_on=issued_on,
        expires_on=expires_on,
        uploaded_by=actor if getattr(actor, "pk", None) else None,
    )
    # El nombre del archivo en disco sale de aquí, no del cliente (RN-61).
    document.validated_extension = checked.extension
    document.stored_path = upload

    try:
        with transaction.atomic():
            # Las restricciones las valida la base: aquí solo los campos, para
            # que un duplicado en carrera llegue como IntegrityError y no como
            # ValidationError a media transacción.
            document.full_clean(exclude=["stored_path"], validate_constraints=False)
            document.save()
    except IntegrityError as error:
        # El índice único por checksum: el mismo archivo ya está en el expediente.
        raise ConflictError("duplicate_document") from error

    record(
        action=AuditAction.DOCUMENT_UPLOAD,
        actor=actor,
        obj=document,
        request=request,
        metadata=_metadata(document),
    )
    return document


def record_download(*, document: EmployeeDocument, actor, request: HttpRequest | None) -> None:
    """Deja constancia de la descarga **antes** de entregar el archivo (RN-63).

    Si el registro falla, la descarga no ocurre: un acceso sin rastro a un
    expediente es peor que un acceso denegado.
    """
    record(
        action=AuditAction.DOCUMENT_DOWNLOAD,
        actor=actor,
        obj=document,
        request=request,
        metadata=_metadata(document),
    )


@transaction.atomic
def archive_document(
    *, document: EmployeeDocument, reason: str, actor, request: HttpRequest | None
) -> EmployeeDocument:
    """Archiva el documento. **No borra el archivo**: un expediente es prueba."""
    document = EmployeeDocument.objects.select_for_update().get(pk=document.pk)
    if not document.is_active:
        raise ConflictError("document_already_archived")

    reason = (reason or "").strip()
    if not reason:
        raise ConflictError("archiving_needs_reason")

    document.is_active = False
    document.archived_reason = reason[:300]
    document.save(update_fields=["is_active", "archived_reason", "updated_at"])

    record(
        action=AuditAction.DOCUMENT_DELETE,
        actor=actor,
        obj=document,
        request=request,
        metadata={**_metadata(document), "reason": reason},
    )
    return document


@transaction.atomic
def create_document_type(*, actor, request: HttpRequest | None, **fields) -> DocumentType:
    """Alta de un tipo. Define qué se acepta y quién lo abre: se audita."""
    document_type = DocumentType(**fields)
    document_type.full_clean()
    document_type.save()
    _ensure_usable(document_type)

    record(
        action=AuditAction.DOCUMENT_TYPE_CREATE,
        actor=actor,
        obj=document_type,
        request=request,
        metadata={"code": document_type.code, "is_sensitive": document_type.is_sensitive},
    )
    return document_type


@transaction.atomic
def update_document_type(
    *, document_type: DocumentType, actor, request: HttpRequest | None, **fields
) -> DocumentType:
    """Edición auditada con el antes y el después de lo que cambió."""
    stored = DocumentType.objects.select_for_update().get(pk=document_type.pk)
    changes = {
        name: {"from": str(getattr(stored, name)), "to": str(value)}
        for name, value in fields.items()
        if getattr(stored, name) != value
    }
    for name, value in fields.items():
        setattr(document_type, name, value)
    document_type.full_clean()
    document_type.save()
    _ensure_usable(document_type)

    record(
        action=AuditAction.DOCUMENT_TYPE_UPDATE,
        actor=actor,
        obj=document_type,
        request=request,
        metadata={"code": document_type.code, "changes": changes},
    )
    return document_type


# --------------------------------------------------------------------------- #
# Internas
# --------------------------------------------------------------------------- #


def _ensure_usable(document_type: DocumentType) -> None:
    """Un tipo sin formatos válidos no acepta nada: sería una trampa."""
    if not document_type.extensions:
        raise ConflictError("type_without_formats")


def _metadata(document: EmployeeDocument) -> dict:
    """Metadata de auditoría: identifica el documento, nunca su contenido."""
    return {
        "employee_code": document.employee.employee_code,
        "document_type": document.document_type.code,
        "public_id": str(document.public_id),
        "is_sensitive": document.document_type.is_sensitive,
        "checksum_sha256": document.checksum_sha256,
    }
