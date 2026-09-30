"""Restricciones de la relación laboral garantizadas por la base de datos."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.contracts.models import Assignment, ContractSalary, EmploymentContract

pytestmark = pytest.mark.django_db

START = dt.date(2025, 1, 1)


def contract_row(employee, company, **overrides) -> EmploymentContract:
    """Fila directa, saltándose los servicios: aquí se prueba la base, no Python."""
    fields = {
        "employee": employee,
        "company": company,
        "contract_type": "INDEFINITE",
        "start_date": START,
        "status": "DRAFT",
        **overrides,
    }
    return EmploymentContract.objects.create(**fields)


# --- RN-13: un solo vínculo vivo ------------------------------------------- #


def test_two_active_contracts_are_rejected(make_employee, company) -> None:
    employee = make_employee()
    contract_row(employee, company, status="ACTIVE")
    with pytest.raises(IntegrityError):
        contract_row(employee, company, status="ACTIVE", start_date=dt.date(2026, 1, 1))


def test_active_plus_suspended_is_also_rejected(make_employee, company) -> None:
    """Refuerzo sobre el diseño original: un suspendido sigue siendo un vínculo vivo."""
    employee = make_employee()
    contract_row(employee, company, status="SUSPENDED")
    with pytest.raises(IntegrityError):
        contract_row(employee, company, status="ACTIVE", start_date=dt.date(2026, 1, 1))


def test_several_closed_contracts_are_allowed(make_employee, company) -> None:
    employee = make_employee()
    for year in (2020, 2022):
        contract_row(
            employee,
            company,
            status="TERMINATED",
            start_date=dt.date(year, 1, 1),
            termination_date=dt.date(year, 12, 31),
            termination_reason="RESIGNATION",
        )
    assert employee.contracts.count() == 2


# --- Tipos y fechas -------------------------------------------------------- #


def test_fixed_term_requires_an_end_date(make_employee, company) -> None:
    with pytest.raises(IntegrityError):
        contract_row(make_employee(), company, contract_type="FIXED_TERM")


def test_indefinite_cannot_have_an_end_date(make_employee, company) -> None:
    with pytest.raises(IntegrityError):
        contract_row(make_employee(), company, end_date=dt.date(2026, 1, 1))


def test_end_cannot_precede_start(make_employee, company) -> None:
    with pytest.raises(IntegrityError):
        contract_row(
            make_employee(), company, contract_type="FIXED_TERM", end_date=dt.date(2024, 1, 1)
        )


def test_terminated_requires_date_and_reason(make_employee, company) -> None:
    with pytest.raises(IntegrityError):
        contract_row(make_employee(), company, status="TERMINATED", termination_date=START)


def test_only_terminated_contracts_carry_a_termination_date(make_employee, company) -> None:
    with pytest.raises(IntegrityError):
        contract_row(make_employee(), company, status="ACTIVE", termination_date=START)


# --- Salario --------------------------------------------------------------- #


def test_salary_must_be_positive(make_employee, company) -> None:
    contract = contract_row(make_employee(), company)
    with pytest.raises(IntegrityError):
        ContractSalary.objects.create(
            contract=contract, amount=0, effective_from=START, change_reason="INITIAL"
        )


def test_only_one_open_salary_per_contract(make_employee, company) -> None:
    """RN-20, por la base."""
    contract = contract_row(make_employee(), company)
    ContractSalary.objects.create(
        contract=contract, amount=5000, effective_from=START, change_reason="INITIAL"
    )
    with pytest.raises(IntegrityError):
        ContractSalary.objects.create(
            contract=contract,
            amount=6000,
            effective_from=dt.date(2025, 6, 1),
            change_reason="MERIT_INCREASE",
        )


@pytest.mark.security
def test_salary_str_never_contains_the_amount(make_employee, company) -> None:
    """`__str__` alimenta la bitácora y los logs."""
    contract = contract_row(make_employee(), company)
    salary = ContractSalary.objects.create(
        contract=contract, amount=Decimal("12345.67"), effective_from=START, change_reason="INITIAL"
    )
    assert "12345" not in str(salary)


@pytest.mark.security
def test_salary_access_has_a_single_permission_path() -> None:
    """Sin permisos por defecto: solo `view_salary` y `change_salary`.

    Dos permisos de vista para el mismo dato invitarían a conceder el equivocado.
    """
    codenames = set(
        Permission.objects.filter(content_type__model="contractsalary").values_list(
            "codename", flat=True
        )
    )
    assert codenames == {"view_salary", "change_salary"}


# --- Asignación ------------------------------------------------------------ #


@pytest.mark.parametrize("fte", [Decimal("0"), Decimal("1.50")])
def test_fte_must_be_within_range(make_employee, company, position, fte) -> None:
    contract = contract_row(make_employee(), company)
    with pytest.raises(IntegrityError):
        Assignment.objects.create(contract=contract, position=position, start_date=START, fte=fte)


def test_only_one_open_primary_assignment(make_employee, company, position, other_position) -> None:
    """RN-24, por la base."""
    contract = contract_row(make_employee(), company)
    Assignment.objects.create(contract=contract, position=position, start_date=START)
    with pytest.raises(IntegrityError):
        Assignment.objects.create(contract=contract, position=other_position, start_date=START)


def test_assignment_has_no_redundant_references() -> None:
    """Ni empleado ni departamento: ambos serían transitivos (3NF, ADR-011)."""
    field_names = {field.name for field in Assignment._meta.get_fields()}
    assert "employee" not in field_names
    assert "department" not in field_names


# --- Borrado --------------------------------------------------------------- #


def test_an_employee_with_contracts_cannot_be_deleted(make_employee, company) -> None:
    employee = make_employee()
    contract_row(employee, company)
    with pytest.raises(ProtectedError):
        employee.delete()


def test_a_position_used_in_an_assignment_cannot_be_deleted(
    make_employee, company, position
) -> None:
    contract = contract_row(make_employee(), company)
    Assignment.objects.create(contract=contract, position=position, start_date=START)
    with pytest.raises(ProtectedError):
        position.delete()
