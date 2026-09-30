"""Reglas del expediente que no son de la cadena de validación."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError
from apps.documents import services
from apps.documents.models import DocumentType
from apps.documents.tests.conftest import PDF_BYTES

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(make_user):
    return make_user("rrhh.servicios.doc@example.com", Role.HR_ADMIN)


def put(employee, document_type, upload, **extra):
    return services.upload_document(
        employee=employee,
        document_type=document_type,
        upload=upload,
        title=extra.pop("title", "Documento"),
        issued_on=extra.pop("issued_on", None),
        expires_on=extra.pop("expires_on", None),
        actor=extra.pop("actor", None),
        request=None,
    )


def test_an_inactive_type_accepts_nothing(make_employee, contract_type, upload) -> None:
    contract_type.is_active = False
    contract_type.save()

    with pytest.raises(ConflictError) as error:
        put(make_employee(), contract_type, upload())

    assert error.value.code == "document_type_inactive"


def test_an_expiry_before_the_issue_date_is_refused(make_employee, contract_type, upload) -> None:
    with pytest.raises(ConflictError) as error:
        put(
            make_employee(),
            contract_type,
            upload(),
            issued_on=dt.date(2026, 5, 1),
            expires_on=dt.date(2026, 4, 1),
        )

    assert error.value.code == "dates_unordered"


# --- Archivado ---------------------------------------------------------------- #


def test_archiving_requires_a_reason(make_employee, contract_type, upload, hr) -> None:
    document = put(make_employee(), contract_type, upload())

    with pytest.raises(ConflictError) as error:
        services.archive_document(document=document, reason="  ", actor=hr, request=None)

    assert error.value.code == "archiving_needs_reason"
    document.refresh_from_db()
    assert document.is_active


def test_a_document_is_archived_only_once(make_employee, contract_type, upload, hr) -> None:
    document = put(make_employee(), contract_type, upload())
    services.archive_document(document=document, reason="Duplicado", actor=hr, request=None)

    with pytest.raises(ConflictError) as error:
        services.archive_document(document=document, reason="Otra vez", actor=hr, request=None)

    assert error.value.code == "document_already_archived"


def test_archiving_frees_the_checksum_for_a_new_upload(
    make_employee, contract_type, upload, hr
) -> None:
    """El índice único solo mira los activos: corregir un error no queda bloqueado."""
    employee = make_employee()
    first = put(employee, contract_type, upload())
    services.archive_document(document=first, reason="Se subió mal", actor=hr, request=None)

    again = put(employee, contract_type, upload())

    assert again.checksum_sha256 == first.checksum_sha256
    assert employee.documents.filter(is_active=True).count() == 1


# --- Catálogo ------------------------------------------------------------------ #


def test_a_type_without_valid_formats_is_not_created(hr) -> None:
    with pytest.raises(ConflictError) as error:
        services.create_document_type(
            actor=hr,
            request=None,
            code="EXE",
            name="Ejecutable",
            allowed_extensions="exe",
            max_size_mb=5,
        )

    assert error.value.code == "type_without_formats"
    assert not DocumentType.objects.filter(code="EXE").exists()


def test_editing_a_type_is_audited_with_its_changes(contract_type, hr) -> None:
    services.update_document_type(
        document_type=contract_type,
        actor=hr,
        request=None,
        name=contract_type.name,
        is_sensitive=True,
        max_size_mb=8,
    )

    event = AuditEvent.objects.get(action=AuditAction.DOCUMENT_TYPE_UPDATE)
    assert event.metadata["changes"] == {
        "is_sensitive": {"from": "False", "to": "True"},
        "max_size_mb": {"from": "5", "to": "8"},
    }


# --- Bitácora ------------------------------------------------------------------- #


@pytest.mark.security
def test_the_audit_log_identifies_the_document_but_not_its_content(
    make_employee, contract_type, upload, hr
) -> None:
    document = put(make_employee(), contract_type, upload(), actor=hr)

    event = AuditEvent.objects.get(action=AuditAction.DOCUMENT_UPLOAD)

    assert event.metadata["checksum_sha256"] == document.checksum_sha256
    assert event.metadata["document_type"] == contract_type.code
    assert PDF_BYTES.decode("latin-1") not in str(event.metadata)


@pytest.mark.security
def test_the_download_is_recorded_with_the_confidential_flag(
    make_employee, medical_type, upload, hr
) -> None:
    document = put(
        make_employee(), medical_type, upload(), expires_on=dt.date(2030, 1, 1), actor=hr
    )

    services.record_download(document=document, actor=hr, request=None)

    event = AuditEvent.objects.get(action=AuditAction.DOCUMENT_DOWNLOAD)
    assert event.metadata["is_sensitive"] is True
