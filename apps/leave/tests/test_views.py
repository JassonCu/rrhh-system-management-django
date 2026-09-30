"""Vistas de ausencias: flujo del asistente, alcance y matriz rol × vista."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.departments.models import Department, DepartmentHeadship
from apps.leave import selectors, services
from apps.leave.constants import LeaveStatus
from apps.leave.models import LeaveEntitlement, LeaveRequest, LeaveType

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker(working, make_employee, make_user):
    """Un EMPLOYEE contratado, con jornada y cuenta propia."""
    account = make_user("ausente@example.com", Role.EMPLOYEE)
    return account, working(employee=make_employee(user=account))


@pytest.fixture
def hr(client, make_user):
    account = make_user("rrhh.vistas@example.com", Role.HR_ADMIN)
    client.force_login(account)
    return account


def pending_request(ask, employee, leave_type) -> LeaveRequest:
    return services.submit_request(
        leave_request=ask(employee, leave_type), actor=employee.user, request=None
    )


# --- Asistente de solicitud ---------------------------------------------------- #


def test_the_wizard_takes_a_request_from_type_to_submission(
    client, worker, vacation, next_monday
) -> None:
    account, employee = worker
    client.force_login(account)

    step1 = client.post(reverse("leave:request_start"), {"leave_type": vacation.pk})
    assert step1.status_code == 302
    assert step1.url == f"{reverse('leave:request_dates')}?type={vacation.pk}"

    step2 = client.post(
        step1.url,
        {
            "start_date": next_monday.isoformat(),
            "end_date": (next_monday + dt.timedelta(days=4)).isoformat(),
            "reason": "",
        },
    )
    leave_request = LeaveRequest.objects.get(employee=employee)
    assert leave_request.status == LeaveStatus.DRAFT
    assert step2.url == reverse("leave:request_review", args=[leave_request.public_id])

    # Revisar es un GET inocuo; enviar exige POST.
    assert client.get(step2.url).status_code == 200
    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.DRAFT

    client.post(step2.url)
    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.SUBMITTED


def test_the_wizard_explains_a_business_rule_failure(client, worker, vacation, next_monday) -> None:
    account, _employee = worker
    client.force_login(account)
    saturday = next_monday + dt.timedelta(days=5)

    response = client.post(
        f"{reverse('leave:request_dates')}?type={vacation.pk}",
        {"start_date": saturday.isoformat(), "end_date": saturday.isoformat()},
        follow=True,
    )

    assert response.status_code == 200
    assert not LeaveRequest.objects.exists()
    assert [str(message) for message in response.context["messages"]]


@pytest.mark.security
def test_the_wizard_ignores_an_employee_in_the_post(
    client, worker, working, vacation, next_monday
) -> None:
    """El titular sale de la sesión: no hay campo que apunte a otra ficha."""
    account, employee = worker
    other = working()
    client.force_login(account)

    client.post(
        f"{reverse('leave:request_dates')}?type={vacation.pk}",
        {
            "start_date": next_monday.isoformat(),
            "end_date": next_monday.isoformat(),
            "employee": other.pk,
        },
    )

    assert LeaveRequest.objects.get().employee == employee


def test_an_inactive_type_is_not_offered(client, worker, vacation) -> None:
    account, _employee = worker
    vacation.is_active = False
    vacation.save()
    client.force_login(account)

    response = client.get(f"{reverse('leave:request_dates')}?type={vacation.pk}")

    assert response.status_code == 404


def test_my_leave_shows_balances(client, worker, vacation, grant) -> None:
    account, employee = worker
    grant(employee, vacation, "7.5")
    client.force_login(account)

    response = client.get(reverse("leave:my_leave"))

    assert response.status_code == 200
    assert response.context["balances"][0]["available"] == Decimal("7.5")


# --- Alcance ------------------------------------------------------------------- #


@pytest.mark.security
def test_someone_elses_request_is_not_found(client, worker, working, vacation, ask) -> None:
    """Fuera de alcance responde 404, no 403: no se confirma que exista."""
    account, _employee = worker
    foreign = ask(working(), vacation)
    client.force_login(account)

    url = reverse("leave:request_detail", args=[foreign.public_id])

    assert client.get(url).status_code == 404


@pytest.mark.security
def test_someone_elses_balance_is_not_found(client, worker, working) -> None:
    account, _employee = worker
    other = working()
    client.force_login(account)

    response = client.get(reverse("leave:employee_balance", args=[other.employee_code]))

    assert response.status_code == 404


# --- Decisiones ---------------------------------------------------------------- #


@pytest.mark.security
def test_approving_by_get_only_shows_the_confirmation(
    client, hr, working, vacation, ask, grant
) -> None:
    employee = working()
    grant(employee, vacation)
    leave_request = services.submit_request(
        leave_request=ask(employee, vacation), actor=None, request=None
    )

    response = client.get(reverse("leave:request_approve", args=[leave_request.public_id]))

    assert response.status_code == 200
    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.SUBMITTED


def test_hr_approves_from_the_inbox(client, hr, working, vacation, ask, grant) -> None:
    employee = working()
    grant(employee, vacation)
    leave_request = services.submit_request(
        leave_request=ask(employee, vacation), actor=None, request=None
    )

    assert leave_request in [
        row["leave_request"] for row in client.get(reverse("leave:inbox")).context["rows"]
    ]

    client.post(reverse("leave:request_approve", args=[leave_request.public_id]), {"note": ""})

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.APPROVED
    assert selectors.balance_for(employee, vacation) == Decimal("5")


def test_a_rejection_without_a_reason_is_refused(client, hr, working, vacation, ask) -> None:
    leave_request = services.submit_request(
        leave_request=ask(working(), vacation), actor=None, request=None
    )

    client.post(reverse("leave:request_reject", args=[leave_request.public_id]), {"note": ""})

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.SUBMITTED


@pytest.mark.security
def test_an_employee_cannot_reach_the_approval_screen(
    client, worker, working, vacation, ask
) -> None:
    account, _employee = worker
    client.force_login(account)
    leave_request = ask(working(), vacation)

    response = client.get(reverse("leave:request_approve", args=[leave_request.public_id]))

    assert response.status_code == 403


def test_the_owner_withdraws_from_the_detail(client, worker, vacation, ask) -> None:
    account, employee = worker
    leave_request = pending_request(ask, employee, vacation)
    client.force_login(account)

    client.post(reverse("leave:request_cancel", args=[leave_request.public_id]), {"note": ""})

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.CANCELLED


# --- Catálogo y saldos: matriz rol × vista -------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.HR_ADMIN, 200),
        (Role.HR_MANAGER, 403),
        (Role.MANAGER, 403),
        (Role.EMPLOYEE, 403),
        (Role.AUDITOR, 403),
    ],
)
def test_only_hr_admin_adjusts_balances(client, make_user, role, expected) -> None:
    client.force_login(make_user(f"ajuste.{role.lower()}@example.com", role))

    assert client.get(reverse("leave:balance_adjust")).status_code == expected


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
def test_only_hr_admin_creates_leave_types(client, make_user, role, expected) -> None:
    client.force_login(make_user(f"tipo.{role.lower()}@example.com", role))

    assert client.get(reverse("leave:type_create")).status_code == expected


@pytest.mark.security
def test_the_auditor_reads_but_cannot_request(client, make_user) -> None:
    client.force_login(make_user("auditora.ausencias@example.com", Role.AUDITOR))

    assert client.get(reverse("leave:type_list")).status_code == 200
    assert client.get(reverse("leave:request_start")).status_code == 403


def test_hr_adjusts_a_balance(client, hr, working, vacation) -> None:
    employee = working()

    client.post(
        reverse("leave:balance_adjust"),
        {"employee": employee.pk, "leave_type": vacation.pk, "days": "4", "note": "Saldo migrado"},
    )

    assert selectors.balance_for(employee, vacation) == Decimal("4")


def test_hr_creates_and_edits_a_leave_type(client, hr) -> None:
    fields = {
        "code": "LUT",
        "name": "Duelo",
        "default_annual_days": "0",
        "min_notice_days": "0",
        "max_backdating_days": "0",
        "requires_approval": "on",
        "is_sensitive": "on",
        "is_active": "on",
    }
    client.post(reverse("leave:type_create"), fields)
    leave_type = LeaveType.objects.get(code="LUT")
    assert leave_type.is_sensitive

    client.post(
        reverse("leave:type_update", args=[leave_type.pk]), {**fields, "name": "Duelo familiar"}
    )

    leave_type.refresh_from_db()
    assert leave_type.name == "Duelo familiar"


def test_an_absurd_annual_allowance_is_refused(client, hr) -> None:
    response = client.post(
        reverse("leave:type_create"),
        {
            "code": "X",
            "name": "X",
            "default_annual_days": "365",
            "min_notice_days": "0",
            "max_backdating_days": "0",
        },
    )

    assert response.status_code == 200
    assert not LeaveType.objects.filter(code="X").exists()


def test_the_calendar_hides_sensitive_types_from_the_page(
    client, make_user, make_employee, working, sick, ask
) -> None:
    """Prueba de extremo a extremo: el nombre del tipo no llega al HTML."""
    manager = make_user("jefa.pagina@example.com", Role.MANAGER)
    DepartmentHeadship.objects.create(
        department=Department.objects.get(code="TI"),
        employee=make_employee(user=manager),
        start_date="2024-01-01",
    )
    leave_request = services.submit_request(
        leave_request=ask(working(), sick), actor=None, request=None
    )
    client.force_login(manager)

    response = client.get(
        reverse("leave:team_calendar"), {"from": leave_request.start_date.isoformat()}
    )

    assert response.status_code == 200
    assert len(response.context["rows"]) == 1
    assert "Incapacidad" not in response.content.decode()


def test_the_calendar_tolerates_a_bad_date(client, hr) -> None:
    assert client.get(reverse("leave:team_calendar"), {"from": "ayer"}).status_code == 200


# --- Devengo mensual ------------------------------------------------------------ #


def test_the_accrual_command_is_idempotent(working, vacation, sick) -> None:
    employee = working()

    call_command("accrue_leave", month="2025-03")
    call_command("accrue_leave", month="2025-03")

    assert LeaveEntitlement.objects.filter(employee=employee).count() == 1
    assert selectors.balance_for(employee, vacation) == Decimal("1.25")
    assert selectors.balance_for(employee, sick) == Decimal("0")


@pytest.mark.security
def test_a_malformed_type_parameter_is_not_found(client, worker) -> None:
    """Un `?type=abc` no debe convertirse en un error 500."""
    account, _employee = worker
    client.force_login(account)

    assert client.get(reverse("leave:request_dates"), {"type": "abc"}).status_code == 404
    assert client.get(reverse("leave:request_dates")).status_code == 404


@pytest.mark.security
def test_the_auditor_cannot_cancel(client, make_user, working, vacation, ask) -> None:
    leave_request = services.submit_request(
        leave_request=ask(working(), vacation), actor=None, request=None
    )
    client.force_login(make_user("auditor.cancela@example.com", Role.AUDITOR))

    detail = client.get(reverse("leave:request_detail", args=[leave_request.public_id]))
    response = client.post(reverse("leave:request_cancel", args=[leave_request.public_id]))

    assert detail.context["can_cancel"] is False
    assert response.status_code == 403
    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.SUBMITTED


@pytest.mark.security
def test_the_adjustment_form_does_not_offer_your_own_record(
    client, hr, working, make_employee
) -> None:
    own = working(employee=make_employee(user=hr))
    other = working()

    offered = client.get(reverse("leave:balance_adjust")).context["form"].fields["employee"]

    assert other in offered.queryset
    assert own not in offered.queryset


def test_creating_a_leave_type_is_audited(client, hr) -> None:
    client.post(
        reverse("leave:type_create"),
        {
            "code": "MAT",
            "name": "Maternidad",
            "default_annual_days": "0",
            "min_notice_days": "0",
            "max_backdating_days": "0",
        },
    )

    assert AuditEvent.objects.filter(action=AuditAction.LEAVE_TYPE_CREATE).exists()
