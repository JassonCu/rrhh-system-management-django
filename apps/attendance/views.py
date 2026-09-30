"""Vistas de asistencia.

Tres capas en cada vista: autenticación, permiso y alcance. El marcaje es
autoservicio: cada quien marca lo suyo, y la vista resuelve la ficha desde la
sesión, nunca desde un parámetro.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.attendance import selectors, services
from apps.attendance.constants import IncidentStatus
from apps.attendance.forms import (
    AdjustEntryForm,
    ResolveIncidentForm,
    ScheduleAssignmentForm,
    WorkScheduleForm,
)
from apps.contracts.selectors import get_contract_or_404
from apps.core.exceptions import ConflictError
from apps.employees.selectors import employees_visible_for

#: Días que muestra «Mi asistencia» hacia atrás.
RECENT_DAYS = 7

ERROR_MESSAGES = {
    "no_live_contract": _("You cannot clock in without a live contract."),
    "entry_already_open": _("There is already an open entry: clock out first."),
    "no_open_entry": _("There is no open entry to close."),
    "check_out_before_check_in": _("The check-out must come after the check-in."),
    "segment_too_long": _("That entry is too long: correct it with an adjustment."),
    "adjustment_needs_reason": _("Adjusting an entry requires a reason."),
    "cannot_change_own_attendance": _("You cannot correct your own attendance."),
    "incident_needs_justification": _("Write the justification before deciding."),
    "incident_already_resolved": _("That incident was already resolved."),
    "invalid_incident_status": _("Choose a valid decision."),
    "schedule_needs_days": _("A schedule needs at least one working day."),
    "schedule_inactive": _("That schedule is inactive."),
    "schedule_outside_contract": _("The start date is outside the contract."),
    "schedule_not_after_previous": _("The new schedule must start after the current one."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


def _own_employee(request: HttpRequest):
    """Ficha de quien tiene la sesión. El marcaje nunca acepta un id por URL."""
    return employees_visible_for(request.user).filter(user=request.user).first()


@login_required
@permission_required("attendance.view_attendanceentry", raise_exception=True)
def my_attendance(request: HttpRequest) -> HttpResponse:
    employee = _own_employee(request)
    today = timezone.localdate()
    context: dict = {"employee": employee, "today": today}

    if employee is not None:
        context["summary"] = selectors.day_summary(employee, today)
        context["recent"] = selectors.period_summary(
            employee, today - dt.timedelta(days=RECENT_DAYS - 1), today
        )[::-1]
        context["incidents"] = employee.attendance_incidents.order_by("-work_date")[:5]

    return render(request, "attendance/my_attendance.html", context)


@login_required
@permission_required("attendance.add_attendanceentry", raise_exception=True)
@require_http_methods(["POST"])
def punch(request: HttpRequest) -> HttpResponse:
    """Marca entrada o salida. El sistema decide cuál toca, no la persona."""
    employee = _own_employee(request)
    if employee is None:
        messages.error(request, _("Your account is not linked to an employee record."))
        return redirect("attendance:my_attendance")

    try:
        if selectors.open_entry_for(employee) is None:
            services.check_in(employee=employee, actor=request.user, request=request)
            messages.success(request, _("Check-in recorded."))
        else:
            services.check_out(employee=employee, actor=request.user, request=request)
            messages.success(request, _("Check-out recorded."))
    except ConflictError as error:
        messages.error(request, _message_for(error))
    return redirect("attendance:my_attendance")


@login_required
@permission_required("attendance.view_attendanceentry", raise_exception=True)
def team_attendance(request: HttpRequest) -> HttpResponse:
    """Asistencia del día para las fichas al alcance de quien consulta."""
    raw_date = request.GET.get("date", "").strip()
    try:
        day = dt.date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        day = timezone.localdate()

    # El resumen consulta por persona, así que la página acota el trabajo: sin
    # paginar, una organización grande dispararía cientos de consultas.
    people = employees_visible_for(request.user).select_related("person")
    page = Paginator(people, 25).get_page(request.GET.get("page"))
    rows = [
        {"employee": employee, "summary": selectors.day_summary(employee, day)} for employee in page
    ]
    return render(request, "attendance/team.html", {"rows": rows, "day": day, "page": page})


@login_required
@permission_required("attendance.view_attendanceincident", raise_exception=True)
def incident_list(request: HttpRequest) -> HttpResponse:
    incidents = selectors.incidents_visible_for(request.user)

    status = request.GET.get("status", "").strip()
    if status in IncidentStatus.values:
        incidents = incidents.filter(status=status)

    page = Paginator(incidents.order_by("-work_date"), 25).get_page(request.GET.get("page"))
    return render(request, "attendance/incident_list.html", {"page": page, "status": status})


@login_required
@permission_required("attendance.change_attendanceincident", raise_exception=True)
@require_http_methods(["GET", "POST"])
def incident_resolve(request: HttpRequest, pk: int) -> HttpResponse:
    incident = selectors.get_incident_or_404(request.user, pk=pk)
    form = ResolveIncidentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            services.resolve_incident(
                incident=incident,
                status=form.cleaned_data["status"],
                justification=form.cleaned_data["justification"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Incident resolved."))
            return redirect("attendance:incident_list")

    return render(request, "attendance/incident_resolve.html", {"form": form, "incident": incident})


@login_required
@permission_required("attendance.adjust_attendance", raise_exception=True)
@require_http_methods(["GET", "POST"])
def entry_adjust(request: HttpRequest, pk: int) -> HttpResponse:
    entry = selectors.get_entry_or_404(request.user, pk=pk)
    form = AdjustEntryForm(
        request.POST or None,
        initial={"check_in_at": entry.check_in_at, "check_out_at": entry.check_out_at},
    )

    if request.method == "POST" and form.is_valid():
        try:
            services.adjust_entry(
                entry=entry,
                check_in_at=form.cleaned_data["check_in_at"],
                check_out_at=form.cleaned_data["check_out_at"],
                reason=form.cleaned_data["reason"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Entry adjusted."))
            return redirect("attendance:team")

    return render(request, "attendance/entry_adjust.html", {"form": form, "entry": entry})


@login_required
@permission_required("attendance.view_workschedule", raise_exception=True)
def schedule_list(request: HttpRequest) -> HttpResponse:
    page = Paginator(selectors.schedules_visible_for(request.user), 25).get_page(
        request.GET.get("page")
    )
    return render(request, "attendance/schedule_list.html", {"page": page})


@login_required
@permission_required("attendance.add_workschedule", raise_exception=True)
@require_http_methods(["GET", "POST"])
def schedule_create(request: HttpRequest) -> HttpResponse:
    form = WorkScheduleForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        fields = {
            name: value
            for name, value in form.cleaned_data.items()
            if name in {"code", "name", "weekly_hours", "grace_minutes", "is_active"}
        }
        try:
            services.create_schedule(
                actor=request.user, request=request, days=form.day_rows(), **fields
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Work schedule created."))
            return redirect("attendance:schedule_list")

    return render(request, "attendance/schedule_form.html", {"form": form})


@login_required
@permission_required("attendance.add_scheduleassignment", raise_exception=True)
@require_http_methods(["GET", "POST"])
def schedule_assign(request: HttpRequest, contract_public_id) -> HttpResponse:
    # El contrato sale de la URL **validada por el selector**, no del formulario.
    contract = get_contract_or_404(request.user, public_id=contract_public_id)
    form = ScheduleAssignmentForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        try:
            services.assign_schedule(
                contract=contract,
                work_schedule=form.cleaned_data["work_schedule"],
                start_date=form.cleaned_data["start_date"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Work schedule assigned."))
            return redirect("contracts:detail", public_id=contract.public_id)

    return render(
        request,
        "attendance/schedule_assign.html",
        {
            "form": form,
            "contract": contract,
            "current": selectors.schedule_assignment_for(contract),
            "cancel_url": reverse("contracts:detail", args=[contract.public_id]),
        },
    )
