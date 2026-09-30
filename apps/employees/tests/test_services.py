"""Casos de uso de empleados: alta, edición y documentos.

La baja se prueba en `contracts`: desde la Fase 4 el estado laboral solo cambia
al terminar un contrato, en la misma transacción (RN-18, ADR-012).
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.test import RequestFactory

from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError
from apps.employees import services
from apps.employees.constants import DocumentType, EmploymentStatus
from apps.employees.models import Person
from apps.employees.tests.conftest import valid_cui

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_with_user(hr_admin):
    request = RequestFactory().post("/empleados/")
    request.user = hr_admin
    return request


def person_data(**overrides) -> dict:
    return {
        "first_name": "Carla",
        "last_name": "Méndez",
        "birth_date": dt.date(1992, 3, 8),
        **overrides,
    }


# --- Alta ------------------------------------------------------------------ #


def test_create_employee_creates_person_and_employee(request_with_user, hr_admin) -> None:
    employee = services.create_employee(
        actor=hr_admin,
        request=request_with_user,
        person_data=person_data(),
        employee_code="emp-0100",
        hire_date=dt.date(2025, 2, 1),
    )
    assert employee.employee_code == "EMP-0100"  # normalizado
    assert employee.employment_status == EmploymentStatus.ACTIVE
    assert employee.person.full_name == "Carla Méndez"


def test_minimum_working_age_is_enforced(request_with_user, hr_admin) -> None:
    """RN-04: cruza Person y Employee, así que no cabe en un CHECK."""
    with pytest.raises(ConflictError) as error:
        services.create_employee(
            actor=hr_admin,
            request=request_with_user,
            person_data=person_data(birth_date=dt.date(2010, 1, 1)),
            employee_code="EMP-0101",
            hire_date=dt.date(2025, 1, 1),
        )
    assert error.value.code == "employee_below_minimum_age"


def test_failed_hire_leaves_no_orphan_person(request_with_user, hr_admin) -> None:
    """El alta es un solo hecho del dominio aunque toque dos tablas."""
    with pytest.raises(ConflictError):
        services.create_employee(
            actor=hr_admin,
            request=request_with_user,
            person_data=person_data(first_name="Huérfana", birth_date=dt.date(2012, 1, 1)),
            employee_code="EMP-0102",
            hire_date=dt.date(2025, 1, 1),
        )
    assert not Person.objects.filter(first_name="Huérfana").exists()


@pytest.mark.security
def test_hire_audit_never_contains_the_birth_date(request_with_user, hr_admin) -> None:
    """La bitácora la lee AUDITOR; la fecha de nacimiento es PII sensible."""
    services.create_employee(
        actor=hr_admin,
        request=request_with_user,
        person_data=person_data(),
        employee_code="EMP-0103",
        hire_date=dt.date(2025, 2, 1),
    )
    event = AuditEvent.objects.get(action=AuditAction.EMPLOYEE_CREATE)
    assert "1992" not in str(event.metadata)
    assert event.metadata["employee_code"] == "EMP-0103"


# --- Edición --------------------------------------------------------------- #


@pytest.mark.security
def test_update_records_changed_fields_not_values(
    request_with_user, hr_admin, employee_record
) -> None:
    """Un diff de PII convertiría la bitácora en una copia del expediente."""
    services.update_person(
        person=employee_record.person,
        actor=hr_admin,
        request=request_with_user,
        last_name="ApellidoSecreto",
    )
    event = AuditEvent.objects.get(action=AuditAction.EMPLOYEE_UPDATE)
    assert event.metadata["changed_fields"] == ["last_name"]
    assert "ApellidoSecreto" not in str(event.metadata)


# --- Documentos --------------------------------------------------------- #


@pytest.mark.security
def test_document_audit_never_contains_the_number(
    request_with_user, hr_admin, employee_record
) -> None:
    cui = valid_cui()
    services.add_identity_document(
        person=employee_record.person,
        actor=hr_admin,
        request=request_with_user,
        document_type=DocumentType.DPI,
        number=cui,
    )
    for event in AuditEvent.objects.all():
        assert cui not in str(event.metadata)
        assert cui not in event.object_repr
