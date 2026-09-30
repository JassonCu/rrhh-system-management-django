"""Invariantes de la relación laboral que viven en los servicios (§E.4)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.contracts import selectors, services
from apps.contracts.models import EmploymentContract
from apps.core.exceptions import ConflictError
from apps.employees.models import Employee

pytestmark = pytest.mark.django_db

START = dt.date(2025, 1, 1)


def conflict_code(callable_, **kwargs) -> str:
    with pytest.raises(ConflictError) as error:
        callable_(**kwargs)
    return error.value.code


# --- Ciclo de vida --------------------------------------------------------- #


def test_hiring_activates_the_contract_and_the_employee(hire) -> None:
    contract = hire()
    assert contract.status == "ACTIVE"
    assert contract.employee.employment_status == "ACTIVE"


def test_activation_requires_an_initial_salary(draft, position) -> None:
    contract = draft()
    services.add_assignment(
        contract=contract, position=position, start_date=START, actor=None, request=None
    )
    assert conflict_code(
        services.activate_contract, contract=contract, actor=None, request=None
    ) == ("contract_needs_salary")


def test_activation_requires_a_primary_position(draft) -> None:
    contract = draft()
    services.set_salary(
        contract=contract,
        amount=Decimal("7000"),
        effective_from=START,
        change_reason="INITIAL",
        actor=None,
        request=None,
    )
    assert conflict_code(
        services.activate_contract, contract=contract, actor=None, request=None
    ) == ("contract_needs_primary_assignment")


@pytest.mark.parametrize(
    ("service", "status"),
    [
        (services.resume_contract, "ACTIVE"),
        (services.activate_contract, "ACTIVE"),
    ],
    ids=["resume_active", "activate_active"],
)
def test_undeclared_transitions_are_rejected(hire, service, status) -> None:
    """La máquina de estados rechaza lo no declarado en lugar de asumirlo."""
    contract = hire()
    assert contract.status == status
    assert conflict_code(service, contract=contract, actor=None, request=None) == (
        "invalid_contract_transition"
    )


def test_a_draft_cannot_be_terminated(draft) -> None:
    code = conflict_code(
        services.terminate_contract,
        contract=draft(),
        termination_date=START,
        reason="RESIGNATION",
        actor=None,
        request=None,
    )
    assert code == "invalid_contract_transition"


def test_suspend_and_resume_follow_the_employee_status(hire) -> None:
    contract = hire()
    services.suspend_contract(contract=contract, actor=None, request=None)
    contract.employee.refresh_from_db()
    assert contract.employee.employment_status == "SUSPENDED"

    services.resume_contract(contract=contract, actor=None, request=None)
    contract.employee.refresh_from_db()
    assert contract.employee.employment_status == "ACTIVE"


# --- RN-13 / RN-14: vínculo único y sin traslape --------------------------- #


def test_a_second_live_contract_cannot_be_activated(hire, draft, position) -> None:
    first = hire()
    second = draft(employee=first.employee, start=dt.date(2027, 1, 1))
    services.set_salary(
        contract=second,
        amount=Decimal("7000"),
        effective_from=second.start_date,
        change_reason="INITIAL",
        actor=None,
        request=None,
    )
    services.add_assignment(
        contract=second, position=position, start_date=second.start_date, actor=None, request=None
    )
    assert conflict_code(services.activate_contract, contract=second, actor=None, request=None) == (
        "employee_has_live_contract"
    )


def _terminate(contract, day: dt.date, actor=None):
    return services.terminate_contract(
        contract=contract, termination_date=day, reason="RESIGNATION", actor=actor, request=None
    )


def _prepare(contract, position, amount=Decimal("7000")):
    services.set_salary(
        contract=contract,
        amount=amount,
        effective_from=contract.start_date,
        change_reason="INITIAL",
        actor=None,
        request=None,
    )
    services.add_assignment(
        contract=contract,
        position=position,
        start_date=contract.start_date,
        actor=None,
        request=None,
    )


def test_overlapping_contracts_are_rejected(hire, draft, position) -> None:
    first = hire()
    _terminate(first, dt.date(2025, 6, 30))
    overlapping = draft(employee=first.employee, start=dt.date(2025, 6, 1))
    _prepare(overlapping, position)

    assert (
        conflict_code(services.activate_contract, contract=overlapping, actor=None, request=None)
        == "contract_overlap"
    )


def test_rehire_after_the_previous_contract_reactivates_the_employee(hire, draft, position) -> None:
    first = hire()
    _terminate(first, dt.date(2025, 6, 30))
    employee = Employee.objects.get(pk=first.employee_id)
    assert employee.employment_status == "TERMINATED"

    rehire = draft(employee=employee, start=dt.date(2025, 7, 1))
    _prepare(rehire, position)
    services.activate_contract(contract=rehire, actor=None, request=None)

    employee.refresh_from_db()
    assert employee.employment_status == "ACTIVE"
    assert employee.termination_date is None


# --- Salario: RN-21, RN-22, RN-23 ------------------------------------------ #


def test_first_salary_must_start_with_the_contract(draft) -> None:
    code = conflict_code(
        services.set_salary,
        contract=draft(),
        amount=Decimal("7000"),
        effective_from=dt.date(2025, 2, 1),
        change_reason="INITIAL",
        actor=None,
        request=None,
    )
    assert code == "first_salary_must_start_with_contract"


def test_a_raise_closes_the_previous_salary_the_day_before(hire) -> None:
    """RN-21: historia contigua, sin huecos ni solapes."""
    contract = hire()
    raise_day = dt.date(2025, 7, 1)
    services.set_salary(
        contract=contract,
        amount=Decimal("8000"),
        effective_from=raise_day,
        change_reason="MERIT_INCREASE",
        actor=None,
        request=None,
    )

    history = list(contract.salaries.order_by("effective_from"))
    assert [salary.amount for salary in history] == [Decimal("7000.00"), Decimal("8000.00")]
    assert history[0].effective_to == raise_day - dt.timedelta(days=1)
    assert history[1].effective_to is None


def test_a_raise_cannot_backdate_the_current_salary(hire) -> None:
    code = conflict_code(
        services.set_salary,
        contract=hire(),
        amount=Decimal("8000"),
        effective_from=START,
        change_reason="ADJUSTMENT",
        actor=None,
        request=None,
    )
    assert code == "salary_not_after_previous"


def test_out_of_band_salary_requires_a_justification(hire) -> None:
    """RN-23: la banda del puesto es 6000-9000."""
    contract = hire()
    kwargs = {
        "contract": contract,
        "amount": Decimal("15000"),
        "effective_from": dt.date(2025, 7, 1),
        "change_reason": "PROMOTION",
        "actor": None,
        "request": None,
    }
    assert (
        conflict_code(services.set_salary, **kwargs) == "salary_out_of_band_requires_justification"
    )

    salary = services.set_salary(
        **kwargs, justification="Retención de talento aprobada por dirección"
    )
    assert salary.justification


@pytest.mark.parametrize(
    ("amount", "frequency", "allowed"),
    [
        (Decimal("900"), "WEEKLY", False),  # 900 × 52 / 12 = 3900 < 4000
        (Decimal("2000"), "BIWEEKLY", True),  # 2000 × 2 = 4000
        (Decimal("3999.99"), "MONTHLY", False),
    ],
)
def test_minimum_wage_uses_the_monthly_equivalent(
    settings, draft, amount, frequency, allowed
) -> None:
    """RN-22: el mínimo es un ajuste de entorno, no una constante."""
    settings.CONTRACTS_MINIMUM_MONTHLY_SALARY = Decimal("4000")
    kwargs = {
        "contract": draft(),
        "amount": amount,
        "pay_frequency": frequency,
        "effective_from": START,
        "change_reason": "INITIAL",
        "actor": None,
        "request": None,
    }
    if allowed:
        services.set_salary(**kwargs)
    else:
        assert conflict_code(services.set_salary, **kwargs) == "salary_below_legal_minimum"


def test_without_a_configured_minimum_nothing_is_checked(settings, draft) -> None:
    settings.CONTRACTS_MINIMUM_MONTHLY_SALARY = None
    services.set_salary(
        contract=draft(),
        amount=Decimal("1"),
        effective_from=START,
        change_reason="INITIAL",
        actor=None,
        request=None,
    )


@pytest.mark.security
def test_salary_audit_never_contains_amounts(hire, hr_admin) -> None:
    """Las cifras viven en ContractSalary, protegidas por `view_salary`."""
    hire(amount=Decimal("7654.32"), actor=hr_admin)
    event = AuditEvent.objects.filter(action=AuditAction.SALARY_CHANGE).get()
    assert event.actor == hr_admin
    assert "7654" not in str(event.metadata)
    assert "7654" not in event.object_repr


# --- Asignaciones: RN-24, RN-25, RN-26 ------------------------------------- #


def test_fte_cannot_exceed_full_time(hire, other_position) -> None:
    code = conflict_code(
        services.add_assignment,
        contract=hire(),
        position=other_position,
        start_date=dt.date(2025, 3, 1),
        fte=Decimal("0.50"),
        is_primary=False,
        actor=None,
        request=None,
    )
    assert code == "fte_exceeds_full_time"


def test_split_positions_within_full_time_are_allowed(draft, position, other_position) -> None:
    contract = draft()
    services.add_assignment(
        contract=contract,
        position=position,
        start_date=START,
        fte=Decimal("0.50"),
        actor=None,
        request=None,
    )
    services.add_assignment(
        contract=contract,
        position=other_position,
        start_date=START,
        fte=Decimal("0.50"),
        is_primary=False,
        actor=None,
        request=None,
    )
    assert contract.assignments.count() == 2


def test_a_transfer_closes_the_previous_primary_position(hire, other_position) -> None:
    contract = hire()
    transfer_day = dt.date(2025, 9, 1)
    services.add_assignment(
        contract=contract,
        position=other_position,
        start_date=transfer_day,
        assignment_reason="TRANSFER",
        actor=None,
        request=None,
    )

    previous, current = contract.assignments.order_by("start_date")
    assert previous.end_date == transfer_day - dt.timedelta(days=1)
    assert current.end_date is None
    assert selectors.current_primary_assignment(contract, transfer_day).position == other_position


def test_a_live_contract_cannot_lose_its_primary_position(hire) -> None:
    contract = hire()
    code = conflict_code(
        services.end_assignment,
        assignment=contract.assignments.get(),
        end_date=dt.date(2025, 5, 1),
        actor=None,
        request=None,
    )
    assert code == "contract_needs_primary_assignment"


def test_assignment_must_fall_within_the_contract(draft, position) -> None:
    code = conflict_code(
        services.add_assignment,
        contract=draft(),
        position=position,
        start_date=dt.date(2024, 12, 31),
        actor=None,
        request=None,
    )
    assert code == "assignment_outside_contract"


def test_an_inactive_position_cannot_be_assigned(draft, position) -> None:
    position.is_active = False
    position.save()
    code = conflict_code(
        services.add_assignment,
        contract=draft(),
        position=position,
        start_date=START,
        actor=None,
        request=None,
    )
    assert code == "position_inactive"


# --- Baja y vencimiento ---------------------------------------------------- #


def test_termination_closes_salary_and_positions_on_the_same_day(hire) -> None:
    contract = hire()
    day = dt.date(2025, 8, 15)
    _terminate(contract, day)

    contract.refresh_from_db()
    assert contract.status == "TERMINATED"
    assert contract.salaries.get().effective_to == day
    assert contract.assignments.get().end_date == day
    employee = Employee.objects.get(pk=contract.employee_id)
    assert employee.employment_status == "TERMINATED"
    assert employee.termination_date == day


@pytest.mark.security
def test_termination_deactivates_the_account_and_closes_sessions(
    client, hire, make_employee, make_user, hr_admin
) -> None:
    """Una cuenta activa de alguien dado de baja es un hallazgo clásico de auditoría."""
    from apps.accounts.constants import Role

    account = make_user("saliente@example.com", Role.EMPLOYEE)
    contract = hire(employee=make_employee(user=account))
    client.force_login(account)

    _terminate(contract, dt.date(2025, 8, 15), actor=hr_admin)

    account.refresh_from_db()
    assert account.is_active is False
    assert client.get("/").status_code == 302


def test_termination_refuses_to_rewrite_a_scheduled_raise(hire) -> None:
    """Un aumento futuro no se cierra con una fecha inventada: se rechaza."""
    contract = hire()
    services.set_salary(
        contract=contract,
        amount=Decimal("8000"),
        effective_from=dt.date(2025, 12, 1),
        change_reason="MERIT_INCREASE",
        actor=None,
        request=None,
    )
    code = conflict_code(
        services.terminate_contract,
        contract=contract,
        termination_date=dt.date(2025, 10, 31),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )
    assert code == "salary_starts_after_termination"


def test_expired_fixed_term_contracts_close_the_employment(hire) -> None:
    contract = hire(contract_type="FIXED_TERM", end_date=dt.date(2025, 3, 31))

    assert services.expire_contracts(today=dt.date(2025, 4, 1)) == 1
    assert services.expire_contracts(today=dt.date(2025, 4, 1)) == 0, "idempotente"

    contract.refresh_from_db()
    assert contract.status == "EXPIRED"
    assert contract.assignments.get().end_date == dt.date(2025, 3, 31)
    employee = Employee.objects.get(pk=contract.employee_id)
    assert employee.employment_status == "TERMINATED"
    assert employee.termination_date == dt.date(2025, 3, 31)


def test_a_contract_is_not_expired_before_its_end(hire) -> None:
    hire(contract_type="FIXED_TERM", end_date=dt.date(2025, 3, 31))
    assert services.expire_contracts(today=dt.date(2025, 3, 31)) == 0


# --- RN-18: invariante de estado laboral ----------------------------------- #


def test_employment_status_stays_consistent_across_the_lifecycle(hire, draft, position) -> None:
    """Prueba de invariante: recorre la base tras un ciclo de vida completo."""
    active = hire()
    suspended = hire()
    services.suspend_contract(contract=suspended, actor=None, request=None)
    ended = hire()
    _terminate(ended, dt.date(2025, 5, 31))
    hire(contract_type="FIXED_TERM", end_date=dt.date(2025, 2, 28))
    services.expire_contracts(today=dt.date(2025, 3, 1))
    draft()  # un borrador no produce efectos

    assert active.status == "ACTIVE"
    assert selectors.find_status_inconsistencies() == []


def test_the_invariant_detects_a_manual_corruption(hire) -> None:
    contract = hire()
    Employee.objects.filter(pk=contract.employee_id).update(employment_status="SUSPENDED")

    problems = selectors.find_status_inconsistencies()

    assert problems == [
        {
            "employee_code": contract.employee.employee_code,
            "actual": "SUSPENDED",
            "expected": "ACTIVE",
        }
    ]


def test_check_command_fails_on_inconsistencies(hire) -> None:
    contract = hire()
    call_command("check_employment_status", stdout=StringIO())

    Employee.objects.filter(pk=contract.employee_id).update(employment_status="SUSPENDED")
    with pytest.raises(CommandError):
        call_command("check_employment_status", stdout=StringIO(), stderr=StringIO())


def test_expire_command_runs() -> None:
    out = StringIO()
    call_command("expire_contracts", stdout=out)
    assert "Contratos vencidos" in out.getvalue()


def test_contracts_are_never_deleted_by_the_lifecycle(hire) -> None:
    contract = hire()
    _terminate(contract, dt.date(2025, 5, 31))
    assert EmploymentContract.objects.filter(pk=contract.pk).exists()
