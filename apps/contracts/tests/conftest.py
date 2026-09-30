"""Fixtures de la relación laboral."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.contracts import services
from apps.departments.models import Department
from apps.employees.tests import conftest as employee_fixtures
from apps.positions.models import JobGrade, Position

START = dt.date(2025, 1, 1)

# Se reutilizan las fábricas de personas y empleados en lugar de duplicarlas.
make_person = employee_fixtures.make_person
make_employee = employee_fixtures.make_employee


@pytest.fixture
def department(company) -> Department:
    return Department.objects.create(company=company, code="TI", name="Tecnología")


@pytest.fixture
def grade() -> JobGrade:
    return JobGrade.objects.create(
        code="G05", name="Profesional", level=5, min_salary=6000, max_salary=9000
    )


@pytest.fixture
def position(department, grade) -> Position:
    return Position.objects.create(
        department=department, job_grade=grade, code="DEV-2", title="Desarrollador II"
    )


@pytest.fixture
def other_position(department, grade) -> Position:
    return Position.objects.create(
        department=department, job_grade=grade, code="ARQ-1", title="Arquitecto"
    )


@pytest.fixture
def draft(company, make_employee):
    """Crea un contrato en borrador, sin salario ni puesto."""

    def _draft(*, employee=None, start=START, contract_type="INDEFINITE", end_date=None):
        return services.create_contract(
            employee=employee or make_employee(),
            actor=None,
            request=None,
            company=company,
            contract_type=contract_type,
            start_date=start,
            end_date=end_date,
        )

    return _draft


@pytest.fixture
def hire(draft, position):
    """Contrata de punta a punta **usando los servicios**, no el ORM.

    Así cada prueba parte de un estado que las invariantes consideran válido, y
    no de filas que nunca podrían existir en producción.
    """

    def _hire(
        *,
        employee=None,
        start=START,
        amount=Decimal("7000"),
        contract_type="INDEFINITE",
        end_date=None,
        on_position=None,
        actor=None,
    ):
        contract = draft(
            employee=employee, start=start, contract_type=contract_type, end_date=end_date
        )
        services.set_salary(
            contract=contract,
            amount=amount,
            effective_from=start,
            change_reason="INITIAL",
            actor=actor,
            request=None,
        )
        services.add_assignment(
            contract=contract,
            position=on_position or position,
            start_date=start,
            actor=actor,
            request=None,
        )
        services.activate_contract(contract=contract, actor=actor, request=None)
        contract.refresh_from_db()
        return contract

    return _hire
