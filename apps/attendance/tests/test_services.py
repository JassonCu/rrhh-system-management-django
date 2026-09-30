"""Invariantes de asistencia que viven en los servicios (§E.4)."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.attendance import selectors, services
from apps.attendance.constants import IncidentStatus, IncidentType
from apps.attendance.tests.conftest import EXPECTED_MINUTES, at
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.contracts import services as contract_services
from apps.core.exceptions import ConflictError

pytestmark = pytest.mark.django_db


def conflict_code(callable_, **kwargs) -> str:
    with pytest.raises(ConflictError) as error:
        callable_(**kwargs)
    return error.value.code


def work_the_day(employee, day, *, start=(8, 0), end=(17, 0)) -> None:
    services.check_in(employee=employee, actor=None, request=None, at=at(day, *start))
    services.check_out(employee=employee, actor=None, request=None, at=at(day, *end))


# --- Marcaje ------------------------------------------------------------------ #


def test_a_day_of_work_is_recorded_and_totalled(working, monday) -> None:
    employee = working()

    work_the_day(employee, monday)

    assert selectors.worked_minutes(employee, monday) == 9 * 60
    assert selectors.expected_minutes(employee, monday) == EXPECTED_MINUTES


def test_without_a_live_contract_nobody_clocks_in(make_employee) -> None:
    """RN-52: marcar presupone una relación laboral vigente."""
    code = conflict_code(services.check_in, employee=make_employee(), actor=None, request=None)
    assert code == "no_live_contract"


def test_a_terminated_person_cannot_clock_in(working, monday) -> None:
    employee = working()
    contract_services.terminate_contract(
        contract=employee.contracts.get(),
        termination_date=dt.date(2025, 2, 28),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )

    assert conflict_code(services.check_in, employee=employee, actor=None, request=None) == (
        "no_live_contract"
    )


def test_two_check_ins_in_a_row_are_rejected(working, monday) -> None:
    employee = working()
    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8))

    code = conflict_code(
        services.check_in, employee=employee, actor=None, request=None, at=at(monday, 9)
    )
    assert code == "entry_already_open"


def test_closing_without_an_open_entry_is_rejected(working) -> None:
    assert conflict_code(services.check_out, employee=working(), actor=None, request=None) == (
        "no_open_entry"
    )


def test_a_segment_cannot_last_forever(working, monday) -> None:
    """Un segmento larguísimo es una salida sin marcar: se corrige, no se acepta."""
    employee = working()
    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8))

    code = conflict_code(
        services.check_out,
        employee=employee,
        actor=None,
        request=None,
        at=at(monday + dt.timedelta(days=1), 6),
    )
    assert code == "segment_too_long"


def test_a_split_shift_adds_up(working, monday) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(12, 0))
    work_the_day(employee, monday, start=(13, 0), end=(17, 0))

    assert selectors.worked_minutes(employee, monday) == 8 * 60


# --- Tolerancia y horas extra ---------------------------------------------------- #


def test_arriving_within_the_grace_period_is_not_late(working, monday) -> None:
    """La jornada de prueba tolera 10 minutos."""
    employee = working()

    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8, 9))

    assert not employee.attendance_incidents.filter(incident_type=IncidentType.LATE).exists()


def test_arriving_after_the_grace_period_opens_a_late_incident(working, monday) -> None:
    employee = working()

    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8, 25))

    incident = employee.attendance_incidents.get(incident_type=IncidentType.LATE)
    assert incident.minutes == 25
    assert incident.status == IncidentStatus.OPEN


def test_the_grace_period_comes_from_the_schedule(working, schedule, monday) -> None:
    """Es un dato por jornada, no una constante del código."""
    schedule.grace_minutes = 30
    schedule.save()
    employee = working()

    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8, 25))

    assert not employee.attendance_incidents.filter(incident_type=IncidentType.LATE).exists()


def test_returning_from_lunch_is_not_a_late_arrival(working, monday) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(12, 0))

    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 13, 30))

    assert not employee.attendance_incidents.filter(incident_type=IncidentType.LATE).exists()


def test_working_longer_opens_an_overtime_incident_that_nobody_approved_yet(
    working, monday
) -> None:
    """Las horas extra nacen abiertas: solo cuentan si alguien las aprueba."""
    employee = working()

    work_the_day(employee, monday, start=(8, 0), end=(19, 0))

    incident = employee.attendance_incidents.get(incident_type=IncidentType.OVERTIME)
    assert incident.minutes == 11 * 60 - EXPECTED_MINUTES
    assert incident.status == IncidentStatus.OPEN


def test_leaving_early_is_only_known_once_the_day_closes(working, monday) -> None:
    """A mediodía nadie se fue temprano: se fue a almorzar."""
    employee = working()

    work_the_day(employee, monday, start=(8, 0), end=(14, 0))
    assert not employee.attendance_incidents.filter(incident_type=IncidentType.EARLY_LEAVE).exists()

    services.close_day(employee=employee, work_date=monday)

    incident = employee.attendance_incidents.get(incident_type=IncidentType.EARLY_LEAVE)
    assert incident.minutes == EXPECTED_MINUTES - 6 * 60


def test_leaving_after_the_shift_ends_is_early_leave_right_away(working, monday) -> None:
    """Si la jornada ya terminó, el defecto se sabe en el acto."""
    employee = working()

    work_the_day(employee, monday, start=(10, 0), end=(17, 30))

    incident = employee.attendance_incidents.get(incident_type=IncidentType.EARLY_LEAVE)
    assert incident.minutes == EXPECTED_MINUTES - 450


def test_not_showing_up_opens_an_absence_when_the_day_closes(working, monday) -> None:
    employee = working()

    services.close_day(employee=employee, work_date=monday)

    incident = employee.attendance_incidents.get(incident_type=IncidentType.ABSENCE)
    assert incident.minutes == EXPECTED_MINUTES


def test_closing_a_day_twice_changes_nothing(working, monday) -> None:
    employee = working()

    services.close_day(employee=employee, work_date=monday)
    services.close_day(employee=employee, work_date=monday)

    assert employee.attendance_incidents.count() == 1


def test_a_public_holiday_expects_no_work(working, monday, company) -> None:
    """En feriado no se espera trabajo: faltar no es ausencia."""
    from apps.core.models import Holiday

    Holiday.objects.create(company=company, date=monday, name="Día de prueba")
    employee = working()

    services.close_day(employee=employee, work_date=monday)

    assert selectors.expected_minutes(employee, monday) == 0
    assert not employee.attendance_incidents.exists()


def test_working_on_a_public_holiday_is_all_overtime(working, monday, company) -> None:
    from apps.core.models import Holiday

    Holiday.objects.create(company=company, date=monday, name="Día de prueba")
    employee = working()

    work_the_day(employee, monday, start=(8, 0), end=(12, 0))

    incident = employee.attendance_incidents.get(incident_type=IncidentType.OVERTIME)
    assert incident.minutes == 4 * 60


def test_closing_a_rest_day_opens_nothing(working) -> None:
    sunday = dt.date(2025, 3, 2)
    employee = working()

    services.close_day(employee=employee, work_date=sunday)

    assert not employee.attendance_incidents.exists()


def test_the_day_is_not_judged_while_a_segment_stays_open(working, monday) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(12, 0))

    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 13))

    assert not employee.attendance_incidents.filter(incident_type=IncidentType.EARLY_LEAVE).exists()


def test_working_on_a_rest_day_is_all_overtime(working) -> None:
    sunday = dt.date(2025, 3, 2)
    employee = working()

    work_the_day(employee, sunday, start=(9, 0), end=(13, 0))

    incident = employee.attendance_incidents.get(incident_type=IncidentType.OVERTIME)
    assert incident.minutes == 4 * 60


# --- Ajustes ---------------------------------------------------------------------- #


def test_adjusting_requires_a_reason(working, monday, hr_admin) -> None:
    """RN-53: una corrección sin motivo no deja explicar qué pasó."""
    employee = working()
    work_the_day(employee, monday)
    entry = employee.attendance_entries.get()

    code = conflict_code(
        services.adjust_entry,
        entry=entry,
        check_in_at=at(monday, 8),
        check_out_at=at(monday, 18),
        reason="  ",
        actor=hr_admin,
        request=None,
    )
    assert code == "adjustment_needs_reason"


def test_an_adjustment_is_audited_with_the_before_and_after(working, monday, hr_admin) -> None:
    employee = working()
    work_the_day(employee, monday)
    entry = employee.attendance_entries.get()

    services.adjust_entry(
        entry=entry,
        check_in_at=at(monday, 8),
        check_out_at=at(monday, 18),
        reason="Olvidó marcar la salida",
        actor=hr_admin,
        request=None,
    )

    event = AuditEvent.objects.get(action=AuditAction.ATTENDANCE_ADJUST)
    assert event.actor == hr_admin
    assert event.metadata["reason"] == "Olvidó marcar la salida"
    assert event.metadata["before"]["check_out_at"] != event.metadata["after"]["check_out_at"]


@pytest.mark.security
def test_nobody_adjusts_their_own_attendance(working, monday, make_user, make_employee) -> None:
    from apps.accounts.constants import Role

    account = make_user("marca.propia@example.com", Role.HR_ADMIN)
    employee = working(employee=make_employee(user=account))
    work_the_day(employee, monday)
    entry = employee.attendance_entries.get()

    code = conflict_code(
        services.adjust_entry,
        entry=entry,
        check_in_at=at(monday, 8),
        check_out_at=at(monday, 19),
        reason="Me quedé más tiempo",
        actor=account,
        request=None,
    )
    assert code == "cannot_change_own_attendance"


def test_an_adjustment_recalculates_the_day(working, monday, hr_admin) -> None:
    employee = working()
    work_the_day(employee, monday)
    entry = employee.attendance_entries.get()

    services.adjust_entry(
        entry=entry,
        check_in_at=at(monday, 8),
        check_out_at=at(monday, 19),
        reason="Marcó salida tarde",
        actor=hr_admin,
        request=None,
    )

    assert employee.attendance_incidents.filter(incident_type=IncidentType.OVERTIME).exists()


# --- Incidencias ------------------------------------------------------------------- #


def test_justifying_an_incident_records_who_and_when(working, monday, hr_admin) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(19, 0))
    incident = employee.attendance_incidents.get(incident_type=IncidentType.OVERTIME)

    services.resolve_incident(
        incident=incident,
        status=IncidentStatus.JUSTIFIED,
        justification="Cierre de mes autorizado",
        actor=hr_admin,
        request=None,
    )

    incident.refresh_from_db()
    assert incident.status == IncidentStatus.JUSTIFIED
    assert incident.resolved_by == hr_admin
    assert incident.resolved_at is not None
    assert AuditEvent.objects.filter(action=AuditAction.ATTENDANCE_INCIDENT_RESOLVE).exists()


def test_resolving_requires_a_justification(working, monday, hr_admin) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(19, 0))
    incident = employee.attendance_incidents.get()

    code = conflict_code(
        services.resolve_incident,
        incident=incident,
        status=IncidentStatus.REJECTED,
        justification="",
        actor=hr_admin,
        request=None,
    )
    assert code == "incident_needs_justification"


def test_a_resolved_incident_is_not_resolved_twice(working, monday, hr_admin) -> None:
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(19, 0))
    incident = employee.attendance_incidents.get()
    services.resolve_incident(
        incident=incident,
        status=IncidentStatus.JUSTIFIED,
        justification="Autorizado",
        actor=hr_admin,
        request=None,
    )

    assert (
        conflict_code(
            services.resolve_incident,
            incident=incident,
            status=IncidentStatus.REJECTED,
            justification="Me arrepentí",
            actor=hr_admin,
            request=None,
        )
        == "incident_already_resolved"
    )


def test_a_resolved_incident_is_not_reopened_by_a_new_calculation(
    working, monday, hr_admin
) -> None:
    """Alguien ya la revisó: recalcular no le pasa por encima."""
    employee = working()
    work_the_day(employee, monday, start=(8, 0), end=(19, 0))
    incident = employee.attendance_incidents.get()
    services.resolve_incident(
        incident=incident,
        status=IncidentStatus.JUSTIFIED,
        justification="Autorizado",
        actor=hr_admin,
        request=None,
    )

    entry = employee.attendance_entries.get()
    services.adjust_entry(
        entry=entry,
        check_in_at=at(monday, 8),
        check_out_at=at(monday, 20),
        reason="Corrección posterior",
        actor=hr_admin,
        request=None,
    )

    incident.refresh_from_db()
    assert incident.status == IncidentStatus.JUSTIFIED
    assert incident.minutes == 11 * 60 - EXPECTED_MINUTES, "no se tocan los minutos ya resueltos"


# --- Jornadas ----------------------------------------------------------------------- #


def test_assigning_a_schedule_closes_the_previous_one(hire, schedule, working) -> None:
    from apps.attendance.models import WorkSchedule

    employee = working()
    contract = employee.contracts.get()
    night = WorkSchedule.objects.create(code="NOC", name="Nocturna", weekly_hours=40)

    services.assign_schedule(
        contract=contract,
        work_schedule=night,
        start_date=dt.date(2025, 4, 1),
        actor=None,
        request=None,
    )

    previous, current = contract.schedule_assignments.order_by("start_date")
    assert previous.end_date == dt.date(2025, 3, 31)
    assert current.work_schedule == night


def test_a_schedule_cannot_start_outside_the_contract(hire, schedule) -> None:
    contract = hire(start=dt.date(2025, 1, 1))

    code = conflict_code(
        services.assign_schedule,
        contract=contract,
        work_schedule=schedule,
        start_date=dt.date(2024, 12, 1),
        actor=None,
        request=None,
    )
    assert code == "schedule_outside_contract"


def test_an_inactive_schedule_cannot_be_assigned(hire, schedule) -> None:
    schedule.is_active = False
    schedule.save()

    assert (
        conflict_code(
            services.assign_schedule,
            contract=hire(),
            work_schedule=schedule,
            start_date=dt.date(2025, 1, 1),
            actor=None,
            request=None,
        )
        == "schedule_inactive"
    )


def test_a_schedule_needs_at_least_one_day(hr_admin) -> None:
    assert (
        conflict_code(
            services.create_schedule,
            actor=hr_admin,
            request=None,
            days=[],
            code="VAC",
            name="Sin días",
            weekly_hours=40,
        )
        == "schedule_needs_days"
    )
