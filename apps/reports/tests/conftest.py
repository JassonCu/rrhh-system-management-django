"""Fixtures de reportes.

Se reutilizan las de ausencias, que ya arrastran empleados, contratos, jornada
y tipos de ausencia: un reporte necesita justamente eso para tener algo que
contar.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents.models import DocumentType
from apps.leave.tests import conftest as leave_fixtures

ask = leave_fixtures.ask
department = leave_fixtures.department
draft = leave_fixtures.draft
errand = leave_fixtures.errand
grade = leave_fixtures.grade
grant = leave_fixtures.grant
hire = leave_fixtures.hire
make_employee = leave_fixtures.make_employee
make_person = leave_fixtures.make_person
next_monday = leave_fixtures.next_monday
other_position = leave_fixtures.other_position
position = leave_fixtures.position
schedule = leave_fixtures.schedule
sick = leave_fixtures.sick
vacation = leave_fixtures.vacation
working = leave_fixtures.working

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def period() -> tuple[dt.date, dt.date]:
    """Una semana laboral de referencia, dentro de la vigencia del contrato."""
    return dt.date(2025, 3, 3), dt.date(2025, 3, 7)


@pytest.fixture
def filters(period):
    from apps.reports.builders import Filters

    start, end = period
    return Filters(date_from=start, date_to=end)


@pytest.fixture
def contract_type(db) -> DocumentType:
    return DocumentType.objects.create(
        code="CON", name="Contrato firmado", allowed_extensions="pdf", max_size_mb=5
    )


@pytest.fixture
def pdf():
    def _pdf(name: str = "contrato.pdf") -> SimpleUploadedFile:
        return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")

    return _pdf


@pytest.fixture
def uncompressed_pdf(monkeypatch):
    """PDF sin comprimir, para poder leer lo impreso en las pruebas.

    En producción se genera comprimido; esto solo cambia el archivo de prueba.
    """
    from reportlab import rl_config

    monkeypatch.setattr(rl_config, "pageCompression", 0)
