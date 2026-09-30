"""Los eventos que antes faltaban: que de verdad se emitan (§K.7).

`test_audit_coverage.py` fija la regla leyendo el código; esta comprueba el
comportamiento: que al ejecutar la operación aparezca el evento.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.constants import Role
from apps.accounts.roles_sync import apply_roles
from apps.attendance import services as attendance_services
from apps.attendance.tests.conftest import at
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.leave import services as leave_services
from apps.leave.tests import conftest as leave_fixtures

# Fixtures de ausencias y asistencia: el escenario mínimo ya trae contrato y jornada.
ask = leave_fixtures.ask
department = leave_fixtures.department
draft = leave_fixtures.draft
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

pytestmark = pytest.mark.django_db


@pytest.mark.security
def test_drafting_a_leave_request_is_recorded(working, vacation, ask) -> None:
    """Un borrador también es una escritura: deja rastro."""
    employee = working()

    ask(employee, vacation)

    event = AuditEvent.objects.get(action=AuditAction.LEAVE_CREATE)
    assert event.metadata["employee_code"] == employee.employee_code
    assert event.metadata["leave_type"] == vacation.code


@pytest.mark.security
def test_the_monthly_accrual_is_recorded(working, vacation) -> None:
    """Mueve el saldo de una persona aunque lo ejecute una tarea programada."""
    employee = working()

    leave_services.accrue_month(
        employee=employee, leave_type=vacation, month_start=dt.date(2025, 3, 1)
    )

    event = AuditEvent.objects.get(action=AuditAction.LEAVE_ACCRUAL)
    assert event.actor is None  # lo ejecuta el sistema
    assert event.metadata["period"] == "2025-03"
    assert Decimal(event.metadata["granted_days"]) == Decimal("1.25")


@pytest.mark.security
def test_punching_for_someone_else_is_recorded(working, make_employee, make_user, monday) -> None:
    """Marcar por cuenta de otra persona es excepcional: por eso sí se audita."""
    account = make_user("marca.por.otro@example.com", Role.HR_MANAGER)
    employee = working()

    attendance_services.check_in(employee=employee, actor=account, request=None, at=at(monday, 8))

    event = AuditEvent.objects.get(action=AuditAction.ATTENDANCE_PUNCH_FOR_OTHER)
    assert event.actor == account
    assert event.metadata["employee_code"] == employee.employee_code


@pytest.mark.security
def test_punching_your_own_attendance_does_not_flood_the_log(
    working, make_employee, make_user, monday
) -> None:
    """Son miles al mes: el registro del marcaje ya es su propia prueba (ADR-021)."""
    account = make_user("marca.lo.suyo@example.com", Role.EMPLOYEE)
    employee = working(employee=make_employee(user=account))

    attendance_services.check_in(employee=employee, actor=account, request=None, at=at(monday, 8))
    attendance_services.check_out(employee=employee, actor=account, request=None, at=at(monday, 17))

    assert not AuditEvent.objects.filter(action=AuditAction.ATTENDANCE_PUNCH_FOR_OTHER).exists()


@pytest.mark.security
def test_changing_the_permissions_of_a_role_is_recorded(db) -> None:
    """«¿Desde cuándo RRHH puede archivar documentos?» tiene que poder responderse."""
    before = AuditEvent.objects.filter(action=AuditAction.PERMISSION_CHANGE).count()

    apply_roles({Role.EMPLOYEE: ("core.view_holiday",)})

    events = AuditEvent.objects.filter(action=AuditAction.PERMISSION_CHANGE)
    assert events.count() > before
    assert events.order_by("-occurred_at").first().metadata["role"] == Role.EMPLOYEE


@pytest.mark.security
def test_asking_for_a_password_reset_is_recorded(client, make_user) -> None:
    """Pedir restablecer una contraseña ajena es la señal temprana de un robo."""
    account = make_user("olvidadiza@example.com", Role.EMPLOYEE)

    client.post(reverse("account_reset_password"), {"email": account.email})

    event = AuditEvent.objects.get(action=AuditAction.PASSWORD_RESET_REQUEST)
    # El correo no entra en la bitácora: la petición aún no está autenticada.
    assert account.email not in str(event.metadata)


@pytest.fixture
def monday() -> dt.date:
    return dt.date(2025, 3, 3)
