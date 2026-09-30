"""Vistas de contratos y correcciones de la revisión de seguridad de la Fase 4.

`test_authorization.py` cubre la matriz rol × vista; aquí se prueban los flujos
completos por HTTP y los hallazgos H-1 a H-5 de
docs/security/revision-fase-4.md.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.contracts import services
from apps.contracts.models import EmploymentContract
from apps.core.exceptions import ConflictError
from apps.core.models import Company
from apps.departments.models import Department
from apps.positions import services as position_services
from apps.positions.models import Position

pytestmark = pytest.mark.django_db


def login(client, make_user, role: str, email: str):
    account = make_user(email, role)
    client.force_login(account)
    return account


def conflict_code(callable_, **kwargs) -> str:
    with pytest.raises(ConflictError) as error:
        callable_(**kwargs)
    return error.value.code


# --- Listado ----------------------------------------------------------------- #


def test_list_filters_by_employee_and_status(client, make_user, hire) -> None:
    wanted, other = hire(), hire()
    login(client, make_user, Role.HR_ADMIN, "filtros@example.com")
    url = reverse("contracts:list")

    by_employee = client.get(url, {"employee": str(wanted.employee.public_id), "status": "ACTIVE"})

    codes = [contract.pk for contract in by_employee.context["page"]]
    assert codes == [wanted.pk]
    assert other.pk not in codes


@pytest.mark.security
def test_a_malformed_employee_filter_returns_nothing(client, make_user, hire) -> None:
    """Un filtro inválido no amplía el resultado ni produce un 500."""
    hire()
    login(client, make_user, Role.HR_ADMIN, "filtro.malo@example.com")

    response = client.get(reverse("contracts:list"), {"employee": "no-es-un-uuid"})

    assert response.status_code == 200
    assert list(response.context["page"]) == []


# --- Flujos por HTTP --------------------------------------------------------- #


def test_terminate_through_the_web(client, make_user, hire) -> None:
    contract = hire()
    login(client, make_user, Role.HR_ADMIN, "baja.web@example.com")

    response = client.post(
        reverse("contracts:terminate", args=[contract.public_id]),
        {"termination_date": "2025-06-30", "termination_reason": "RESIGNATION"},
    )

    assert response.status_code == 302
    contract.refresh_from_db()
    assert contract.status == "TERMINATED"


def test_end_a_secondary_assignment_through_the_web(
    client, make_user, draft, position, other_position
) -> None:
    contract = draft()
    services.add_assignment(
        contract=contract,
        position=position,
        start_date=contract.start_date,
        fte=Decimal("0.50"),
        actor=None,
        request=None,
    )
    secondary = services.add_assignment(
        contract=contract,
        position=other_position,
        start_date=contract.start_date,
        fte=Decimal("0.50"),
        is_primary=False,
        actor=None,
        request=None,
    )
    login(client, make_user, Role.HR_ADMIN, "fin.asig@example.com")

    client.post(
        reverse("contracts:assignment_end", args=[contract.public_id, secondary.pk]),
        {"end_date": "2025-03-31"},
    )

    secondary.refresh_from_db()
    assert secondary.end_date == dt.date(2025, 3, 31)


def test_a_rejected_salary_keeps_the_form_and_explains(client, make_user, draft) -> None:
    contract = draft()
    login(client, make_user, Role.HR_ADMIN, "salario.malo@example.com")

    response = client.post(
        reverse("contracts:salary_set", args=[contract.public_id]),
        {
            "amount": "7000.00",
            "currency": "GTQ",
            "pay_frequency": "MONTHLY",
            "effective_from": "2025-02-01",  # no coincide con el inicio del contrato
            "change_reason": "INITIAL",
        },
    )

    assert response.status_code == 200
    assert not contract.salaries.exists()
    assert [str(message) for message in response.context["messages"]]


def test_an_invalid_end_date_is_reported(client, make_user, hire) -> None:
    contract = hire()
    login(client, make_user, Role.HR_ADMIN, "fecha.mala@example.com")

    response = client.post(
        reverse(
            "contracts:assignment_end", args=[contract.public_id, contract.assignments.get().pk]
        ),
        {"end_date": "ayer"},
        follow=True,
    )

    assert response.status_code == 200
    assert contract.assignments.get().end_date is None


# --- H-1: separación de funciones -------------------------------------------- #


@pytest.fixture
def hr_admin_with_contract(make_user, make_employee, hire):
    """Una responsable de RRHH que también es empleada, con su propio contrato."""
    account = make_user("rrhh.empleada@example.com", Role.HR_ADMIN)
    return account, hire(employee=make_employee(user=account))


@pytest.mark.security
def test_nobody_raises_their_own_salary(hr_admin_with_contract) -> None:
    account, contract = hr_admin_with_contract
    code = conflict_code(
        services.set_salary,
        contract=contract,
        amount=Decimal("9000"),
        effective_from=dt.date(2025, 7, 1),
        change_reason="MERIT_INCREASE",
        actor=account,
        request=None,
    )
    assert code == "cannot_change_own_employment"
    assert contract.salaries.count() == 1


@pytest.mark.security
def test_nobody_promotes_themselves(hr_admin_with_contract, other_position) -> None:
    account, contract = hr_admin_with_contract
    code = conflict_code(
        services.add_assignment,
        contract=contract,
        position=other_position,
        start_date=dt.date(2025, 7, 1),
        actor=account,
        request=None,
    )
    assert code == "cannot_change_own_employment"


@pytest.mark.security
@pytest.mark.parametrize("service", [services.suspend_contract, services.activate_contract])
def test_nobody_changes_the_status_of_their_own_contract(hr_admin_with_contract, service) -> None:
    account, contract = hr_admin_with_contract
    assert conflict_code(service, contract=contract, actor=account, request=None) == (
        "cannot_change_own_employment"
    )


@pytest.mark.security
def test_nobody_creates_a_contract_for_themselves(make_user, make_employee, company) -> None:
    account = make_user("autocontrato@example.com", Role.HR_ADMIN)
    own_record = make_employee(user=account)
    code = conflict_code(
        services.create_contract,
        employee=own_record,
        actor=account,
        request=None,
        company=company,
        contract_type="INDEFINITE",
        start_date=dt.date(2025, 1, 1),
    )
    assert code == "cannot_change_own_employment"
    assert not EmploymentContract.objects.filter(employee=own_record).exists()


@pytest.mark.security
def test_the_web_explains_the_segregation_rule(client, hr_admin_with_contract) -> None:
    account, contract = hr_admin_with_contract
    client.force_login(account)

    response = client.post(reverse("contracts:suspend", args=[contract.public_id]), follow=True)

    assert response.status_code == 200
    contract.refresh_from_db()
    assert contract.status == "ACTIVE"


@pytest.mark.security
def test_a_colleague_can_still_act_on_that_contract(hr_admin_with_contract, make_user) -> None:
    """La regla es sobre quién, no un bloqueo del contrato."""
    _account, contract = hr_admin_with_contract
    colleague = make_user("colega.rrhh@example.com", Role.HR_ADMIN)
    services.suspend_contract(contract=contract, actor=colleague, request=None)
    contract.refresh_from_db()
    assert contract.status == "SUSPENDED"


# --- H-2: consultas de salario de terceros ----------------------------------- #


@pytest.mark.security
def test_a_third_party_salary_view_is_audited(client, make_user, hire) -> None:
    contract = hire(amount=Decimal("7000"))
    viewer = login(client, make_user, Role.AUDITOR, "mira.salarios@example.com")

    client.get(reverse("contracts:detail", args=[contract.public_id]))

    event = AuditEvent.objects.get(action=AuditAction.SALARY_VIEW)
    assert event.actor == viewer
    assert "7000" not in str(event.metadata)


@pytest.mark.security
def test_viewing_your_own_salary_is_not_audited(client, make_user, make_employee, hire) -> None:
    account = make_user("mi.salario@example.com", Role.EMPLOYEE)
    contract = hire(employee=make_employee(user=account))
    client.force_login(account)

    client.get(reverse("contracts:detail", args=[contract.public_id]))

    assert not AuditEvent.objects.filter(action=AuditAction.SALARY_VIEW).exists()


@pytest.mark.security
def test_opening_a_contract_without_salary_access_is_not_a_salary_view(
    client, make_user, hire
) -> None:
    contract = hire()
    login(client, make_user, Role.HR_MANAGER, "sin.importes@example.com")

    client.get(reverse("contracts:detail", args=[contract.public_id]))

    assert not AuditEvent.objects.filter(action=AuditAction.SALARY_VIEW).exists()


# --- H-3: el admin no esquiva los servicios ---------------------------------- #


@pytest.mark.security
def test_contract_admin_is_read_only(superuser) -> None:
    """Ni siquiera un superusuario edita contratos desde el admin."""
    request = RequestFactory().get("/")
    request.user = superuser
    model_admin = admin.site._registry[EmploymentContract]

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False
    for inline in model_admin.get_inline_instances(request):
        assert inline.has_add_permission(request, None) is False
        assert inline.has_change_permission(request) is False


# --- H-4: bajas con fecha futura --------------------------------------------- #


@pytest.mark.security
def test_a_future_termination_is_rejected(hire) -> None:
    """Cortaría hoy el acceso de alguien que sigue trabajando."""
    contract = hire()
    code = conflict_code(
        services.terminate_contract,
        contract=contract,
        termination_date=timezone.localdate() + dt.timedelta(days=1),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )
    assert code == "termination_in_future"
    contract.refresh_from_db()
    assert contract.status == "ACTIVE"


def test_a_termination_today_is_allowed(hire) -> None:
    contract = hire()
    services.terminate_contract(
        contract=contract,
        termination_date=timezone.localdate(),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )


# --- H-5: integridad entre empresas ------------------------------------------ #


@pytest.mark.security
def test_a_position_of_another_company_cannot_be_assigned(draft, grade) -> None:
    other_company = Company.objects.create(
        code="OTRA", legal_name="Otra Empresa, S.A.", tax_id="7654321-0", country="GT"
    )
    foreign = Position.objects.create(
        department=Department.objects.create(company=other_company, code="FIN", name="Finanzas"),
        job_grade=grade,
        code="FIN-1",
        title="Contador",
    )
    code = conflict_code(
        services.add_assignment,
        contract=draft(),
        position=foreign,
        start_date=dt.date(2025, 1, 1),
        actor=None,
        request=None,
    )
    assert code == "position_in_another_company"


# --- Deuda de la Fase 3: puestos ocupados ------------------------------------ #


def test_an_occupied_position_cannot_be_deactivated(hire, position, hr_admin) -> None:
    hire()
    request = RequestFactory().post("/")
    request.user = hr_admin
    code = conflict_code(
        position_services.deactivate_position, position=position, actor=hr_admin, request=request
    )
    assert code == "position_is_occupied"


def test_a_position_committed_to_a_draft_is_also_occupied(draft, position) -> None:
    contract = draft()
    services.add_assignment(
        contract=contract,
        position=position,
        start_date=contract.start_date,
        actor=None,
        request=None,
    )
    code = conflict_code(
        position_services.deactivate_position, position=position, actor=None, request=None
    )
    assert code == "position_is_occupied"


def test_a_position_is_free_once_the_contract_ends(hire, position) -> None:
    contract = hire()
    services.terminate_contract(
        contract=contract,
        termination_date=dt.date(2025, 6, 30),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )
    position_services.deactivate_position(position=position, actor=None, request=None)
    position.refresh_from_db()
    assert position.is_active is False


# --- UX-2: elegir puesto por área (ADR-011) ---------------------------------- #


def test_the_position_select_is_grouped_by_department(
    client, make_user, hire, position, other_position, company, grade
) -> None:
    """Sin JavaScript, los <optgroup> ya permiten ubicar el puesto por área."""
    from apps.departments.models import Department
    from apps.positions.models import Position

    other_area = Department.objects.create(company=company, code="RRHH", name="Recursos Humanos")
    Position.objects.create(
        department=other_area, job_grade=grade, code="RH-1", title="Analista de personal"
    )
    contract = hire()
    login(client, make_user, Role.HR_ADMIN, "agrupado@example.com")

    content = client.get(
        reverse("contracts:assignment_add", args=[contract.public_id])
    ).content.decode()

    assert '<optgroup label="Tecnología">' in content
    assert '<optgroup label="Recursos Humanos">' in content
    assert "data-grouped-select" in content, "main.js añade el filtro por área"


@pytest.mark.security
def test_the_grouped_select_still_only_offers_visible_positions(
    client, make_user, hire, position
) -> None:
    """Agrupar es presentación: el alcance lo sigue imponiendo el selector."""
    contract = hire()
    login(client, make_user, Role.HR_ADMIN, "agrupado.alcance@example.com")

    form = client.get(reverse("contracts:assignment_add", args=[contract.public_id])).context[
        "form"
    ]

    assert list(form.fields["position"].queryset) == [position]


def test_the_web_explains_why_a_position_stays_active(client, make_user, hire, position) -> None:
    hire()
    login(client, make_user, Role.HR_ADMIN, "puesto.ocupado@example.com")

    response = client.post(reverse("positions:deactivate", args=[position.pk]), follow=True)

    assert response.status_code == 200
    position.refresh_from_db()
    assert position.is_active is True
