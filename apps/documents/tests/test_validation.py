"""Cadena de validación de subida (§K.4). Es el criterio de cierre de la fase."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction

from apps.core.exceptions import ConflictError
from apps.documents import services
from apps.documents.constants import MAX_SIZE_MB
from apps.documents.models import DocumentType, EmployeeDocument
from apps.documents.tests.conftest import DOCX_BYTES, EXE_BYTES, PDF_BYTES, PNG_BYTES
from apps.documents.validators import safe_display_name

pytestmark = pytest.mark.django_db


def upload_for(employee, document_type, file, **extra):
    return services.upload_document(
        employee=employee,
        document_type=document_type,
        upload=file,
        title=extra.pop("title", "Contrato 2026"),
        issued_on=extra.pop("issued_on", None),
        expires_on=extra.pop("expires_on", None),
        actor=None,
        request=None,
        **extra,
    )


# --- Lo que sí se acepta ---------------------------------------------------- #


def test_a_real_pdf_is_stored(make_employee, contract_type, upload, media) -> None:
    employee = make_employee()

    document = upload_for(employee, contract_type, upload())

    stored = Path(document.stored_path.path)
    assert stored.is_file()
    assert stored.read_bytes() == PDF_BYTES
    assert document.size_bytes == len(PDF_BYTES)
    assert document.checksum_sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
    assert Path(media) in stored.parents


def test_the_stored_name_is_generated_not_the_uploaded_one(
    make_employee, contract_type, upload
) -> None:
    """RN-61: el nombre del cliente no toca el sistema de archivos."""
    employee = make_employee()

    document = upload_for(employee, contract_type, upload(name="mi contrato firmado.pdf"))

    stored_name = Path(document.stored_path.name).name
    assert stored_name != "mi contrato firmado.pdf"
    assert stored_name.endswith(".pdf")
    assert str(employee.public_id) in document.stored_path.name
    # Lo que la persona subió se conserva, pero solo para mostrarlo.
    assert document.original_filename == "mi contrato firmado.pdf"


@pytest.mark.parametrize(
    ("name", "content", "content_type"),
    [
        pytest.param("foto.png", PNG_BYTES, "image/png", id="png"),
        pytest.param(
            "titulo.docx",
            DOCX_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            id="docx",
        ),
    ],
)
def test_other_allowed_formats_pass(make_employee, upload, name, content, content_type) -> None:
    document_type = DocumentType.objects.create(
        code="VAR", name="Varios", allowed_extensions="png,docx", max_size_mb=5
    )

    document = upload_for(
        make_employee(),
        document_type,
        upload(name=name, content=content, content_type=content_type),
    )

    assert document.size_bytes == len(content)


# --- Lo que no pasa --------------------------------------------------------- #


@pytest.mark.security
def test_an_executable_renamed_to_pdf_is_refused(make_employee, contract_type, upload) -> None:
    """El caso clásico: el nombre dice PDF y el contenido es un ejecutable."""
    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), contract_type, upload(name="nomina.pdf", content=EXE_BYTES))

    assert error.value.code == "content_does_not_match_extension"
    assert not EmployeeDocument.objects.exists()


@pytest.mark.security
def test_a_traversal_file_name_leaves_no_path(make_employee, contract_type, upload, media) -> None:
    """`../../etc/passwd.pdf` no debe escribir fuera de MEDIA_ROOT ni conservar ruta."""
    employee = make_employee()

    document = upload_for(employee, contract_type, upload(name="../../../etc/passwd.pdf"))

    assert ".." not in document.original_filename
    assert "/" not in document.original_filename
    assert "\\" not in document.original_filename
    assert Path(media).resolve() in Path(document.stored_path.path).resolve().parents


@pytest.mark.security
def test_an_oversized_file_is_refused(make_employee, contract_type, upload) -> None:
    oversized = PDF_BYTES + b"0" * (contract_type.max_size_mb * 1024 * 1024)

    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), contract_type, upload(content=oversized))

    assert error.value.code == "file_too_large"
    assert error.value.context == {"limit": contract_type.max_size_mb}


@pytest.mark.security
def test_the_global_cap_wins_over_the_type(make_employee, upload) -> None:
    """Un tipo no puede autorizar más de 25 MB, diga lo que diga el catálogo."""
    generous = DocumentType.objects.create(
        code="BIG", name="Grande", allowed_extensions="pdf", max_size_mb=MAX_SIZE_MB
    )

    with pytest.raises(ConflictError) as error:
        upload_for(
            make_employee(),
            generous,
            upload(content=PDF_BYTES + b"0" * (MAX_SIZE_MB * 1024 * 1024)),
        )

    assert error.value.context == {"limit": MAX_SIZE_MB}


@pytest.mark.security
def test_an_extension_outside_the_allowlist_is_refused(
    make_employee, contract_type, upload
) -> None:
    with pytest.raises(ConflictError) as error:
        upload_for(
            make_employee(),
            contract_type,
            upload(name="foto.png", content=PNG_BYTES, content_type="image/png"),
        )

    assert error.value.code == "extension_not_allowed"


@pytest.mark.security
def test_a_file_without_extension_is_refused(make_employee, contract_type, upload) -> None:
    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), contract_type, upload(name="contrato"))

    assert error.value.code == "extension_not_allowed"


@pytest.mark.security
def test_a_lying_content_type_is_refused(make_employee, contract_type, upload) -> None:
    """Se comprueba aunque no se confíe: si miente, algo raro pasa."""
    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), contract_type, upload(content_type="application/x-msdownload"))

    assert error.value.code == "content_type_mismatch"


def test_an_empty_file_is_refused(make_employee, contract_type, upload) -> None:
    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), contract_type, upload(content=b""))

    assert error.value.code == "empty_file"


def test_a_type_without_valid_formats_accepts_nothing(make_employee, upload) -> None:
    broken = DocumentType.objects.create(code="ROTO", name="Roto", allowed_extensions="exe,sh")

    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), broken, upload())

    assert error.value.code == "type_without_formats"


def test_the_same_file_is_not_uploaded_twice(make_employee, contract_type, upload) -> None:
    employee = make_employee()
    upload_for(employee, contract_type, upload())

    with pytest.raises(ConflictError) as error:
        upload_for(employee, contract_type, upload(name="otro-nombre.pdf"))

    assert error.value.code == "duplicate_document"
    assert employee.documents.count() == 1


def test_an_expiry_is_required_when_the_type_says_so(make_employee, medical_type, upload) -> None:
    with pytest.raises(ConflictError) as error:
        upload_for(make_employee(), medical_type, upload())

    assert error.value.code == "expiry_required"


# --- Saneo del nombre para mostrar y descargar ------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ('nombre"raro.pdf', "nombreraro.pdf"),
        ("cabecera\r\ninyectada.pdf", "cabecerainyectada.pdf"),
        ("C:\\Users\\ana\\hoja.pdf", "hoja.pdf"),
        ("   ", "documento"),
    ],
)
def test_the_display_name_cannot_inject_headers_or_paths(raw, expected) -> None:
    assert safe_display_name(raw) == expected


# --- Lo que impone la base --------------------------------------------------- #


def test_the_database_refuses_a_bad_checksum(make_employee, contract_type) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        EmployeeDocument.objects.create(
            employee=make_employee(),
            document_type=contract_type,
            title="X",
            stored_path="documents/x.pdf",
            original_filename="x.pdf",
            size_bytes=10,
            checksum_sha256="corto",
        )


def test_the_database_refuses_an_expiry_before_the_issue_date(make_employee, contract_type) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        EmployeeDocument.objects.create(
            employee=make_employee(),
            document_type=contract_type,
            title="X",
            stored_path="documents/x.pdf",
            original_filename="x.pdf",
            size_bytes=10,
            checksum_sha256="a" * 64,
            issued_on=dt.date(2026, 5, 1),
            expires_on=dt.date(2026, 4, 1),
        )
