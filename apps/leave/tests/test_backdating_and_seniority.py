"""Registro retroactivo y días por antigüedad (decisiones P-1 y P-2 de la Fase 6)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError
from apps.leave import selectors, services
from apps.leave.forms import LeaveTypeForm
from apps.leave.models import LeaveAccrualTier, LeaveRequest, LeaveType

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(make_user):
    return make_user("rrhh.antiguedad@example.com", Role.HR_ADMIN)


@pytest.fixture
def wednesday(next_monday, monkeypatch):
    """Fija «hoy» en un miércoles: el lunes de esa semana queda dos días atrás."""
    today = next_monday + dt.timedelta(days=2)
    monkeypatch.setattr(services.timezone, "localdate", lambda *_args: today)
    return today


def allow_backdating(leave_type, days: int) -> None:
    leave_type.max_backdating_days = days
    leave_type.save()


# --- Registro retroactivo -------------------------------------------------------- #


def test_an_accident_can_be_reported_two_days_later(
    working, sick, ask, next_monday, wednesday
) -> None:
    """El caso del negocio: se accidenta el lunes y lo reportan el miércoles."""
    allow_backdating(sick, 5)

    leave_request = ask(working(), sick, start=next_monday, days=2)

    assert leave_request.working_days == Decimal("2")


def test_a_type_without_backdating_must_start_today_or_later(
    working, vacation, ask, next_monday, wednesday
) -> None:
    with pytest.raises(ConflictError) as error:
        ask(working(), vacation, start=next_monday, days=1)

    assert error.value.code == "too_far_in_the_past"


def test_the_backdating_window_is_a_limit(working, sick, ask, next_monday, wednesday) -> None:
    allow_backdating(sick, 1)

    with pytest.raises(ConflictError) as error:
        ask(working(), sick, start=next_monday, days=1)

    assert error.value.code == "too_far_in_the_past"
    assert error.value.context == {"allowed": 1}


def test_a_forgotten_draft_cannot_be_submitted_out_of_the_window(
    working, sick, ask, next_monday, monkeypatch
) -> None:
    """El plazo se revalida al enviar, no solo al crear."""
    allow_backdating(sick, 3)
    monkeypatch.setattr(services.timezone, "localdate", lambda *_args: next_monday)
    leave_request = ask(working(), sick, start=next_monday, days=1)

    monkeypatch.setattr(
        services.timezone, "localdate", lambda *_args: next_monday + dt.timedelta(days=10)
    )
    with pytest.raises(ConflictError) as error:
        services.submit_request(leave_request=leave_request, actor=None, request=None)

    assert error.value.code == "too_far_in_the_past"


@pytest.mark.security
def test_backdated_registrations_are_visible_in_the_audit_log(
    working, sick, ask, next_monday, wednesday
) -> None:
    """El registro retroactivo es donde más se presta a abuso: queda a la vista."""
    allow_backdating(sick, 5)
    leave_request = ask(working(), sick, start=next_monday, days=1)
    registered = dt.datetime.combine(wednesday, dt.time(10), tzinfo=dt.UTC)
    LeaveRequest.objects.filter(pk=leave_request.pk).update(created_at=registered)

    services.submit_request(leave_request=leave_request, actor=None, request=None)

    assert AuditEvent.objects.get(action=AuditAction.LEAVE_SUBMIT).metadata["backdated_days"] == 2


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"max_backdating_days": 31}, id="window-too-long"),
        pytest.param({"max_backdating_days": 5, "min_notice_days": 3}, id="notice-and-backdating"),
    ],
)
def test_the_database_refuses_incoherent_windows(fields) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveType.objects.create(code="X", name="X", **fields)


def test_the_form_explains_notice_and_backdating_cannot_coexist() -> None:
    form = LeaveTypeForm(
        {
            "code": "X",
            "name": "X",
            "default_annual_days": "0",
            "min_notice_days": "3",
            "max_backdating_days": "5",
        }
    )

    assert not form.is_valid()
    assert form.has_error("__all__", code="notice_or_backdating")


# --- Antigüedad ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    ("on", "years"),
    [
        (dt.date(2024, 1, 14), 0),
        (dt.date(2025, 1, 14), 0),
        (dt.date(2025, 1, 15), 1),
        (dt.date(2030, 6, 1), 6),
    ],
)
def test_years_of_service_count_completed_years(make_employee, on, years) -> None:
    employee = make_employee(hire_date=dt.date(2024, 1, 15))

    assert selectors.years_of_service(employee, on) == years


@pytest.fixture
def tiered(vacation, hr):
    """Vacaciones: 15 base, 18 desde el año 3 y 20 desde el año 5."""
    for min_years, days in ((3, "18"), (5, "20")):
        services.add_accrual_tier(
            leave_type=vacation,
            min_years_of_service=min_years,
            annual_days=Decimal(days),
            actor=hr,
            request=None,
        )
    return vacation


@pytest.mark.parametrize(("years", "days"), [(0, "15"), (2, "15"), (3, "18"), (4, "18"), (9, "20")])
def test_the_highest_reached_tier_applies(tiered, years, days) -> None:
    assert selectors.annual_days_for(tiered, years) == Decimal(days)


def test_accrual_follows_seniority(working, tiered) -> None:
    """Ingreso en 2024-01-15 (fábrica de empleados): en 2030-03 lleva 6 años."""
    employee = working()

    entitlement = services.accrue_month(
        employee=employee, leave_type=tiered, month_start=dt.date(2030, 3, 1)
    )

    assert entitlement.granted_days == Decimal("1.67")  # 20 / 12
    assert "years=6 annual=20" in employee.leave_ledger.get().note


def test_a_newcomer_accrues_the_base(working, tiered) -> None:
    employee = working()

    entitlement = services.accrue_month(
        employee=employee, leave_type=tiered, month_start=dt.date(2025, 3, 1)
    )

    assert entitlement.granted_days == Decimal("1.25")  # 15 / 12


@pytest.mark.parametrize(
    ("years", "days", "code"),
    [
        pytest.param(1, "10", "tier_below_base", id="below-the-legal-base"),
        pytest.param(4, "17", "tier_below_previous", id="fewer-than-a-lower-tier"),
        pytest.param(4, "21", "tier_above_next", id="more-than-a-higher-tier"),
        pytest.param(3, "19", "tier_already_exists", id="duplicate-years"),
    ],
)
def test_more_seniority_never_means_fewer_days(tiered, hr, years, days, code) -> None:
    """«Conforme a la legislación y sin ser injustos»."""
    with pytest.raises(ConflictError) as error:
        services.add_accrual_tier(
            leave_type=tiered,
            min_years_of_service=years,
            annual_days=Decimal(days),
            actor=hr,
            request=None,
        )

    assert error.value.code == code


def test_raising_the_base_above_a_tier_is_refused(tiered, hr) -> None:
    with pytest.raises(ConflictError) as error:
        services.update_leave_type(
            leave_type=tiered, actor=hr, request=None, default_annual_days=Decimal("19")
        )

    assert error.value.code == "base_above_a_tier"


def test_a_tier_starts_after_the_first_year(vacation) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveAccrualTier.objects.create(
            leave_type=vacation, min_years_of_service=0, annual_days=Decimal("15")
        )


def test_the_accrual_command_includes_types_with_only_tiers(working, hr) -> None:
    bonus = LeaveType.objects.create(code="ANT", name="Días por antigüedad")
    services.add_accrual_tier(
        leave_type=bonus, min_years_of_service=5, annual_days=Decimal("6"), actor=hr, request=None
    )
    employee = working()

    call_command("accrue_leave", month="2030-03")

    assert selectors.balance_for(employee, bonus) == Decimal("0.50")


# --- Pantallas de tramos --------------------------------------------------------- #


@pytest.mark.security
def test_only_hr_admin_manages_tiers(client, make_user, vacation) -> None:
    client.force_login(make_user("rrhh.gestor@example.com", Role.HR_MANAGER))

    response = client.post(
        reverse("leave:tier_add", args=[vacation.pk]),
        {"min_years_of_service": 3, "annual_days": "18"},
    )

    assert response.status_code == 403
    assert not vacation.accrual_tiers.exists()


def test_hr_adds_and_removes_a_tier(client, hr, vacation) -> None:
    client.force_login(hr)
    client.post(
        reverse("leave:tier_add", args=[vacation.pk]),
        {"min_years_of_service": 3, "annual_days": "18"},
    )
    tier = vacation.accrual_tiers.get()

    remove_url = reverse("leave:tier_remove", args=[vacation.pk, tier.pk])
    assert client.get(remove_url).status_code == 200  # confirmación, no borra
    assert vacation.accrual_tiers.exists()

    client.post(remove_url)

    assert not vacation.accrual_tiers.exists()
    assert AuditEvent.objects.filter(action=AuditAction.LEAVE_TYPE_UPDATE).count() == 2


def test_an_unfair_tier_is_explained_not_saved(client, hr, vacation) -> None:
    client.force_login(hr)

    response = client.post(
        reverse("leave:tier_add", args=[vacation.pk]),
        {"min_years_of_service": 2, "annual_days": "10"},
        follow=True,
    )

    assert not vacation.accrual_tiers.exists()
    assert [str(message) for message in response.context["messages"]]


def test_the_type_page_lists_its_tiers(client, hr, tiered) -> None:
    client.force_login(hr)

    response = client.get(reverse("leave:type_update", args=[tiered.pk]))

    assert response.status_code == 200
    assert list(response.context["tiers"].values_list("min_years_of_service", flat=True)) == [3, 5]


# --- Lo que el devengo tiene que cuadrar ------------------------------------------ #


@pytest.mark.parametrize("annual", ["15", "18", "20", "22", "17.5"])
def test_twelve_months_add_up_to_the_year(working, vacation, annual) -> None:
    """Redondear cada mes por separado inventaba o perdía días al cabo del año."""
    vacation.default_annual_days = Decimal(annual)
    vacation.save()
    employee = working()

    for month in range(1, 13):
        services.accrue_month(
            employee=employee, leave_type=vacation, month_start=dt.date(2026, month, 1)
        )

    assert selectors.balance_for(employee, vacation) == Decimal(annual)


def test_a_month_before_the_hire_date_is_not_accrued(working, vacation, make_employee) -> None:
    """Nadie devenga un mes en el que todavía no trabajaba."""
    employee = working(employee=make_employee(hire_date=dt.date(2025, 6, 10)))

    assert (
        services.accrue_month(
            employee=employee, leave_type=vacation, month_start=dt.date(2025, 1, 1)
        )
        is None
    )
    assert selectors.balance_for(employee, vacation) == Decimal("0")


def test_the_period_must_be_a_whole_month(working, vacation) -> None:
    """Un «mes» que empieza el día 15 rompería el índice único del período."""
    with pytest.raises(ConflictError) as error:
        services.accrue_month(
            employee=working(), leave_type=vacation, month_start=dt.date(2026, 3, 15)
        )

    assert error.value.code == "month_must_start_the_month"


# --- El saldo se comprueba en todos los caminos ----------------------------------- #


@pytest.mark.security
def test_a_type_without_approval_still_respects_the_balance(working, errand, ask) -> None:
    """Auto-aprobarse no puede ser la puerta de atrás para gastar días que no hay."""
    errand.allows_negative_balance = False
    errand.save()
    employee = working()

    with pytest.raises(ConflictError) as error:
        services.submit_request(
            leave_request=ask(employee, errand, days=2), actor=None, request=None
        )

    assert error.value.code == "insufficient_balance"
    assert not employee.leave_ledger.exists()


def test_a_type_without_approval_consumes_what_it_has(working, errand, ask, grant) -> None:
    employee = working()
    errand.allows_negative_balance = False
    errand.save()
    grant(employee, errand, "5")

    services.submit_request(leave_request=ask(employee, errand, days=2), actor=None, request=None)

    assert selectors.balance_for(employee, errand) == Decimal("3")
