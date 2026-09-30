"""Alcance, confidencialidad y matriz rol × vista del expediente (§J.2, §J.7)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.documents import selectors, services
from apps.documents.models import DocumentType, EmployeeDocument
from apps.documents.tests.conftest import PDF_BYTES, PNG_BYTES

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr_admin(make_user):
    return make_user("rrhh.expediente@example.com", Role.HR_ADMIN)


@pytest.fixture
def worker(make_employee, make_user):
    account = make_user("empleada.expediente@example.com", Role.EMPLOYEE)
    return account, make_employee(user=account)


def put(employee, document_type, upload, **extra) -> EmployeeDocument:
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


# --- Subida ------------------------------------------------------------------ #


def test_hr_uploads_from_the_view(client, hr_admin, make_employee, contract_type, upload) -> None:
    employee = make_employee()
    client.force_login(hr_admin)

    response = client.post(
        reverse("documents:upload", args=[employee.public_id]),
        {"document_type": contract_type.pk, "title": "Contrato 2026", "file": upload()},
    )

    assert response.status_code == 302
    document = employee.documents.get()
    assert document.uploaded_by == hr_admin
    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_UPLOAD).exists()


@pytest.mark.security
def test_an_employee_only_uploads_the_allowed_types(
    client, worker, diploma_type, contract_type, upload
) -> None:
    """«P (tipos permitidos)»: su diploma sí, un contrato no."""
    account, employee = worker
    client.force_login(account)
    url = reverse("documents:upload", args=[employee.public_id])

    refused = client.post(
        url, {"document_type": contract_type.pk, "title": "Mi contrato", "file": upload()}
    )
    accepted = client.post(
        url, {"document_type": diploma_type.pk, "title": "Mi diploma", "file": upload()}
    )

    assert refused.status_code == 200  # el formulario no lo ofrece
    assert accepted.status_code == 302
    assert employee.documents.get().document_type == diploma_type


@pytest.mark.security
def test_nobody_uploads_to_someone_elses_file(
    client, worker, make_employee, diploma_type, upload
) -> None:
    account, _employee = worker
    stranger = make_employee()
    client.force_login(account)

    response = client.post(
        reverse("documents:upload", args=[stranger.public_id]),
        {"document_type": diploma_type.pk, "title": "X", "file": upload()},
    )

    assert response.status_code == 404  # fuera de alcance: ni existe, para él
    assert not stranger.documents.exists()


@pytest.mark.security
def test_a_manager_has_no_access_to_files(
    client, make_user, make_employee, contract_type, upload
) -> None:
    """La matriz §J.2 deja el expediente fuera del alcance de la jefatura.

    Se usa su **propia** ficha a propósito: es la que con seguridad está a su
    alcance, así que lo que falla aquí es el permiso, no el alcance.
    """
    account = make_user("jefe.expediente@example.com", Role.MANAGER)
    employee = make_employee(user=account)
    put(employee, contract_type, upload())
    client.force_login(account)

    listing = client.get(f"{reverse('employees:detail', args=[employee.public_id])}?tab=file")
    download = client.get(reverse("documents:download", args=[employee.documents.get().public_id]))

    assert listing.context["can_view_documents"] is False
    assert download.status_code == 403


# --- Descarga ----------------------------------------------------------------- #


def test_downloading_delivers_the_file_and_leaves_a_trace(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    document = put(make_employee(), contract_type, upload())
    client.force_login(hr_admin)

    response = client.get(reverse("documents:download", args=[document.public_id]))

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF_BYTES
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in response["Content-Disposition"]
    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_DOWNLOAD).count() == 1


@pytest.mark.security
def test_someone_elses_document_is_not_found(
    client, worker, make_employee, contract_type, upload
) -> None:
    account, _employee = worker
    foreign = put(make_employee(), contract_type, upload())
    client.force_login(account)

    response = client.get(reverse("documents:download", args=[foreign.public_id]))

    assert response.status_code == 404
    assert not AuditEvent.objects.filter(action=AuditAction.DOCUMENT_DOWNLOAD).exists()


@pytest.mark.security
def test_media_is_not_served_directly(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    """Un enlace filtrado a `/media/` no debe servir de llave (§K.4)."""
    document = put(make_employee(), contract_type, upload())
    client.force_login(hr_admin)

    response = client.get(f"/media/{document.stored_path.name}")

    assert response.status_code == 404


@pytest.mark.security
def test_a_confidential_document_is_visible_but_not_openable(
    client, make_user, make_employee, medical_type, upload
) -> None:
    """Se sabe que existe —RRHH lo necesita— pero no se abre sin permiso."""
    employee = make_employee()
    document = put(
        employee,
        medical_type,
        upload(name="incapacidad.png", content=PNG_BYTES, content_type="image/png"),
        expires_on=timezone.localdate() + dt.timedelta(days=60),
    )
    hr_manager = make_user("rrhh.gestora.exp@example.com", Role.HR_MANAGER)
    client.force_login(hr_manager)

    listing = client.get(f"{reverse('employees:detail', args=[employee.public_id])}?tab=file")
    download = client.get(reverse("documents:download", args=[document.public_id]))

    assert [row["can_open"] for row in listing.context["file_documents"]] == [False]
    assert "incapacidad.png" not in listing.content.decode()
    assert download.status_code == 403
    assert not AuditEvent.objects.filter(action=AuditAction.DOCUMENT_DOWNLOAD).exists()


@pytest.mark.security
def test_the_owner_cannot_open_an_hr_confidential_document(
    client, worker, medical_type, upload
) -> None:
    account, employee = worker
    document = put(
        employee,
        medical_type,
        upload(),
        expires_on=timezone.localdate() + dt.timedelta(days=60),
    )
    client.force_login(account)

    assert client.get(reverse("documents:download", args=[document.public_id])).status_code == 403


def test_hr_admin_and_the_auditor_do_open_it(
    client, hr_admin, make_user, make_employee, medical_type, upload
) -> None:
    document = put(
        make_employee(),
        medical_type,
        upload(),
        expires_on=timezone.localdate() + dt.timedelta(days=60),
    )
    auditor = make_user("auditora.expediente@example.com", Role.AUDITOR)

    for account in (hr_admin, auditor):
        client.force_login(account)
        assert (
            client.get(reverse("documents:download", args=[document.public_id])).status_code == 200
        )

    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_DOWNLOAD).count() == 2


def test_the_owner_downloads_their_own_ordinary_document(
    client, worker, diploma_type, upload
) -> None:
    account, employee = worker
    document = put(employee, diploma_type, upload())
    client.force_login(account)

    assert client.get(reverse("documents:download", args=[document.public_id])).status_code == 200


# --- Archivado ---------------------------------------------------------------- #


@pytest.mark.security
def test_archiving_by_get_only_shows_the_confirmation(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    document = put(make_employee(), contract_type, upload())
    client.force_login(hr_admin)

    response = client.get(reverse("documents:archive", args=[document.public_id]))

    document.refresh_from_db()
    assert response.status_code == 200
    assert document.is_active


def test_archiving_keeps_the_file_and_leaves_a_trace(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    document = put(make_employee(), contract_type, upload())
    stored = document.stored_path.path
    client.force_login(hr_admin)

    client.post(
        reverse("documents:archive", args=[document.public_id]), {"reason": "Subido por error"}
    )

    document.refresh_from_db()
    assert document.is_active is False
    assert document.archived_reason == "Subido por error"
    assert Path(stored).is_file()  # un expediente es prueba: no se borra
    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_DELETE).exists()


def test_an_archived_document_leaves_the_record(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    employee = make_employee()
    document = put(employee, contract_type, upload())
    services.archive_document(document=document, reason="Error", actor=hr_admin, request=None)
    client.force_login(hr_admin)

    listing = client.get(f"{reverse('employees:detail', args=[employee.public_id])}?tab=file")

    assert listing.context["file_documents"] == []
    assert selectors.documents_visible_for(hr_admin, include_archived=True).count() == 1


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.HR_ADMIN, 200),
        (Role.HR_MANAGER, 403),
        (Role.EMPLOYEE, 403),
        (Role.AUDITOR, 403),
    ],
)
def test_only_hr_admin_archives(
    client, make_user, make_employee, contract_type, upload, role, expected
) -> None:
    document = put(make_employee(), contract_type, upload())
    client.force_login(make_user(f"archiva.{role.lower()}@example.com", role))

    response = client.get(reverse("documents:archive", args=[document.public_id]))

    assert response.status_code == expected


# --- Catálogo y vencimientos ---------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.HR_ADMIN, 200),
        (Role.HR_MANAGER, 403),
        (Role.EMPLOYEE, 403),
        (Role.AUDITOR, 403),
    ],
)
def test_only_hr_admin_edits_the_catalogue(client, make_user, role, expected) -> None:
    client.force_login(make_user(f"tipo.doc.{role.lower()}@example.com", role))

    assert client.get(reverse("documents:type_create")).status_code == expected


def test_creating_a_type_is_audited(client, hr_admin) -> None:
    client.force_login(hr_admin)

    client.post(
        reverse("documents:type_create"),
        {
            "code": "CAR",
            "name": "Carta de renuncia",
            "allowed_extensions": "PDF, .pdf",
            "max_size_mb": 5,
            "retention_years": 5,
            "is_active": "on",
        },
    )

    assert DocumentType.objects.get(code="CAR").allowed_extensions == "pdf"
    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_TYPE_CREATE).exists()


def test_a_type_with_unknown_formats_is_refused(client, hr_admin) -> None:
    client.force_login(hr_admin)

    response = client.post(
        reverse("documents:type_create"),
        {"code": "EXE", "name": "Ejecutable", "allowed_extensions": "exe", "max_size_mb": 5},
    )

    assert response.status_code == 200
    assert response.context["form"].has_error("allowed_extensions")


def test_the_expiring_list_shows_what_needs_chasing(
    client, hr_admin, make_employee, medical_type, upload
) -> None:
    employee = make_employee()
    today = timezone.localdate()
    put(employee, medical_type, upload(), expires_on=today + dt.timedelta(days=10))
    put(
        employee,
        medical_type,
        upload(name="otra.png", content=PNG_BYTES, content_type="image/png"),
        expires_on=today + dt.timedelta(days=200),
    )
    client.force_login(hr_admin)

    response = client.get(reverse("documents:expiring"))

    assert [document.expires_on for document in response.context["page"]] == [
        today + dt.timedelta(days=10)
    ]


def test_hr_edits_a_type_from_the_view(client, hr_admin, contract_type) -> None:
    client.force_login(hr_admin)

    response = client.post(
        reverse("documents:type_update", args=[contract_type.pk]),
        {
            "code": contract_type.code,
            "name": "Contrato laboral firmado",
            "allowed_extensions": "pdf",
            "max_size_mb": 7,
            "retention_years": 10,
            "is_active": "on",
        },
    )

    contract_type.refresh_from_db()
    assert response.status_code == 302
    assert contract_type.name == "Contrato laboral firmado"
    assert contract_type.max_size_mb == 7
    assert AuditEvent.objects.filter(action=AuditAction.DOCUMENT_TYPE_UPDATE).exists()


@pytest.mark.security
def test_an_archived_document_can_no_longer_be_downloaded(
    client, hr_admin, make_employee, contract_type, upload
) -> None:
    """Archivar es la única forma de retirar un documento: tiene que cortar el acceso.

    La pantalla de archivado se lo promete a quien confirma; si el enlace
    guardado siguiera funcionando, la promesa sería falsa.
    """
    document = put(make_employee(), contract_type, upload())
    url = reverse("documents:download", args=[document.public_id])
    client.force_login(hr_admin)
    assert client.get(url).status_code == 200

    services.archive_document(
        document=document, reason="Subido a la ficha equivocada", actor=hr_admin, request=None
    )

    assert client.get(url).status_code == 404


@pytest.mark.security
def test_an_employee_is_never_offered_a_confidential_type(
    client, worker, medical_type, upload
) -> None:
    """Aunque el catálogo lo marque como suyo: no podría volver a abrirlo."""
    account, employee = worker
    medical_type.employee_can_upload = True
    medical_type.save()
    client.force_login(account)

    response = client.post(
        reverse("documents:upload", args=[employee.public_id]),
        {"document_type": medical_type.pk, "title": "Mi constancia", "file": upload()},
    )

    assert response.status_code == 200  # el formulario no lo ofrece
    assert not employee.documents.exists()
