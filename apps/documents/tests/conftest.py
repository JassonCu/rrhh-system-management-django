"""Fixtures del expediente documental.

Cada prueba escribe en su propio `MEDIA_ROOT` temporal: ninguna deja archivos en
el repositorio ni ve los de otra.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import DocumentType
from apps.employees.tests import conftest as employee_fixtures

make_employee = employee_fixtures.make_employee
make_person = employee_fixtures.make_person

#: Contenidos mínimos con la firma real de cada formato (§K.4).
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
DOCX_BYTES = b"PK\x03\x04" + b"0" * 64
#: Un ejecutable de Windows: empieza con «MZ», diga lo que diga su nombre.
EXE_BYTES = b"MZ\x90\x00" + b"0" * 64


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def upload():
    """Archivo subido, con el nombre y el `content_type` que diga la prueba."""

    def _upload(
        name: str = "contrato.pdf",
        content: bytes = PDF_BYTES,
        content_type: str = "application/pdf",
    ) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, content, content_type=content_type)

    return _upload


@pytest.fixture
def contract_type(db) -> DocumentType:
    """Contrato firmado: PDF, 5 MB, lo sube RRHH."""
    return DocumentType.objects.create(
        code="CON", name="Contrato firmado", allowed_extensions="pdf", max_size_mb=5
    )


@pytest.fixture
def medical_type(db) -> DocumentType:
    """Expediente médico: confidencial y con vencimiento obligatorio."""
    return DocumentType.objects.create(
        code="MED",
        name="Expediente médico",
        allowed_extensions="pdf,png",
        max_size_mb=5,
        is_sensitive=True,
        requires_expiry=True,
    )


@pytest.fixture
def diploma_type(db) -> DocumentType:
    """Diploma: es de los tipos que la propia persona puede subir."""
    return DocumentType.objects.create(
        code="DIP",
        name="Diploma",
        allowed_extensions="pdf,png,jpg",
        max_size_mb=5,
        employee_can_upload=True,
    )
