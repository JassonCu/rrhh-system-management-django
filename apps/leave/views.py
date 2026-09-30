"""Vistas de ausencias.

Tres capas en cada vista: autenticación, permiso y alcance. El alcance va
**antes** que el permiso: una solicitud fuera de alcance responde 404, no 403,
para no confirmar que existe (§J.4).

El asistente de solicitud no guarda nada en la sesión: el paso intermedio es la
propia solicitud en estado `DRAFT`, igual que el asistente de contratación. Así
un cierre de navegador no pierde el trabajo y el estado siempre está en la base.
"""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import ConflictError
from apps.employees.selectors import employees_visible_for
from apps.leave import selectors, services
from apps.leave.constants import LeaveStatus
from apps.leave.forms import (
    AccrualTierForm,
    BalanceAdjustmentForm,
    DecisionForm,
    LeaveDatesStepForm,
    LeaveTypeForm,
    LeaveTypeStepForm,
)

#: Ventana por defecto del calendario de equipo.
CALENDAR_DAYS = 14

#: Estados en los que quien solicita puede retirar su solicitud.
WITHDRAWABLE = (LeaveStatus.DRAFT, LeaveStatus.SUBMITTED)

#: Estados en los que quien aprueba puede cancelar. El servicio lo vuelve a
#: comprobar todo: esto solo decide si se muestra el botón.
CANCELLABLE_BY_APPROVER = (LeaveStatus.SUBMITTED, LeaveStatus.APPROVED)

ERROR_MESSAGES = {
    "no_live_contract": _("You cannot request leave without a live contract."),
    "leave_type_inactive": _("That leave type is no longer available."),
    "dates_unordered": _("The end date cannot be earlier than the start date."),
    "overlapping_request": _("You already have leave requested for those dates."),
    "not_enough_notice": _("That type requires more advance notice."),
    "base_above_a_tier": _("The base days cannot exceed a seniority tier."),
    "tier_already_exists": _("That type already has a tier for those years."),
    "tier_below_base": _("A tier cannot grant fewer days than the base of the type."),
    "tier_below_previous": _("A tier cannot grant fewer days than a lower seniority tier."),
    "tier_above_next": _("A tier cannot grant more days than a higher seniority tier."),
    "too_far_in_the_past": _("That type cannot be registered that long after it started."),
    "no_working_days": _("There are no working days in that range."),
    "invalid_leave_transition": _("That request can no longer change to that state."),
    "not_your_request": _("That request is not yours to change."),
    "cannot_approve": _("You cannot decide on that request."),
    "cannot_cancel_approved": _("Only an approver can cancel an approved leave."),
    "insufficient_balance": _("There is not enough balance for those days."),
    "rejection_needs_reason": _("Rejecting a request requires a reason."),
    "leave_already_started": _("That leave already started: it cannot be cancelled."),
    "adjustment_needs_reason": _("An adjustment requires a reason."),
    "adjustment_needs_days": _("An adjustment of zero days changes nothing."),
    "cannot_adjust_own_balance": _("You cannot adjust your own leave balance."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


def _own_employee(request: HttpRequest):
    """Ficha de quien tiene la sesión. Nunca sale de un parámetro."""
    return employees_visible_for(request.user).filter(user=request.user).first()


# --------------------------------------------------------------------------- #
# Lo propio
# --------------------------------------------------------------------------- #


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def my_leave(request: HttpRequest) -> HttpResponse:
    employee = _own_employee(request)
    context: dict = {"employee": employee}

    if employee is not None:
        context["balances"] = selectors.balances_for(employee)
        context["page"] = Paginator(
            selectors.own_requests(request.user).order_by("-start_date"), 15
        ).get_page(request.GET.get("page"))
        context["ledger"] = selectors.ledger_for(employee)[:10]

    return render(request, "leave/my_leave.html", context)


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def request_detail(request: HttpRequest, public_id) -> HttpResponse:
    leave_request = selectors.get_request_or_404(request.user, public_id=public_id)
    is_owner = leave_request.employee.user_id == request.user.pk
    can_decide = selectors.can_approve(request.user, leave_request)
    return render(
        request,
        "leave/request_detail.html",
        {
            "leave_request": leave_request,
            "transitions": leave_request.transitions.select_related("actor").order_by("created_at"),
            "is_owner": is_owner,
            "can_decide": can_decide,
            "can_cancel": request.user.has_perm("leave.add_leaverequest")
            and (
                (is_owner and leave_request.status in WITHDRAWABLE)
                or (can_decide and leave_request.status in CANCELLABLE_BY_APPROVER)
            ),
            "balance": selectors.balance_for(leave_request.employee, leave_request.leave_type),
        },
    )


# --------------------------------------------------------------------------- #
# Asistente de solicitud
# --------------------------------------------------------------------------- #


@login_required
@permission_required("leave.add_leaverequest", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_start(request: HttpRequest) -> HttpResponse:
    """Paso 1: el tipo. Se elige aparte porque cambia las reglas del paso 2."""
    form = LeaveTypeStepForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        leave_type = form.cleaned_data["leave_type"]
        return redirect(f"{reverse('leave:request_dates')}?type={leave_type.pk}")

    employee = _own_employee(request)
    return render(
        request,
        "leave/request_start.html",
        {"form": form, "employee": employee, "step": 1, "steps": 3},
    )


@login_required
@permission_required("leave.add_leaverequest", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_dates(request: HttpRequest) -> HttpResponse:
    """Paso 2: fechas y motivo. Al guardar queda un borrador, aún sin enviar."""
    raw_type = request.GET.get("type", "")
    if not raw_type.isdigit():
        raise Http404
    leave_type = get_object_or_404(
        selectors.types_visible_for(request.user).filter(is_active=True), pk=int(raw_type)
    )
    employee = _own_employee(request)
    if employee is None:
        messages.error(request, _("Your account is not linked to an employee record."))
        return redirect("leave:my_leave")

    form = LeaveDatesStepForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            leave_request = services.create_request(
                employee=employee,
                leave_type=leave_type,
                start_date=form.cleaned_data["start_date"],
                end_date=form.cleaned_data["end_date"],
                reason=form.cleaned_data["reason"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            return redirect("leave:request_review", public_id=leave_request.public_id)

    return render(
        request,
        "leave/request_dates.html",
        {
            "form": form,
            "leave_type": leave_type,
            "balance": selectors.balance_for(employee, leave_type),
            "step": 2,
            "steps": 3,
        },
    )


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_review(request: HttpRequest, public_id) -> HttpResponse:
    """Paso 3: revisar y enviar. Enviar es un `POST`, nunca un enlace."""
    leave_request = selectors.get_request_or_404(request.user, public_id=public_id)
    if leave_request.status != LeaveStatus.DRAFT:
        return redirect("leave:request_detail", public_id=leave_request.public_id)

    balance = selectors.balance_for(leave_request.employee, leave_request.leave_type)
    pending = selectors.pending_days_for(
        leave_request.employee, leave_request.leave_type, exclude=leave_request
    )
    if request.method == "POST":
        try:
            services.submit_request(
                leave_request=leave_request, actor=request.user, request=request
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Leave request submitted."))
            return redirect("leave:request_detail", public_id=leave_request.public_id)

    return render(
        request,
        "leave/request_review.html",
        {
            "leave_request": leave_request,
            "balance": balance,
            "pending_days": pending,
            "balance_after": balance - pending - leave_request.working_days,
            "step": 3,
            "steps": 3,
        },
    )


# --------------------------------------------------------------------------- #
# Decisiones
# --------------------------------------------------------------------------- #


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def inbox(request: HttpRequest) -> HttpResponse:
    """Bandeja de aprobación. Lista solo lo que este usuario puede decidir."""
    pending = list(selectors.pending_for(request.user))
    rows = [
        {
            "leave_request": item,
            "balance": selectors.balance_for(item.employee, item.leave_type),
        }
        for item in pending
    ]
    return render(request, "leave/inbox.html", {"rows": rows})


@login_required
@permission_required("leave.approve_leave", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_approve(request: HttpRequest, public_id) -> HttpResponse:
    leave_request = selectors.get_request_or_404(request.user, public_id=public_id)
    form = DecisionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            services.approve_request(
                leave_request=leave_request,
                actor=request.user,
                request=request,
                note=form.cleaned_data["note"],
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Leave request approved."))
            return redirect("leave:inbox")

    return render(
        request,
        "leave/request_decide.html",
        _decision_context(leave_request, form, decision="approve"),
    )


@login_required
@permission_required("leave.approve_leave", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_reject(request: HttpRequest, public_id) -> HttpResponse:
    leave_request = selectors.get_request_or_404(request.user, public_id=public_id)
    form = DecisionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            services.reject_request(
                leave_request=leave_request,
                actor=request.user,
                request=request,
                note=form.cleaned_data["note"],
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Leave request rejected."))
            return redirect("leave:inbox")

    return render(
        request,
        "leave/request_decide.html",
        _decision_context(leave_request, form, decision="reject"),
    )


@login_required
@permission_required("leave.add_leaverequest", raise_exception=True)
@require_http_methods(["GET", "POST"])
def request_cancel(request: HttpRequest, public_id) -> HttpResponse:
    """Cancelar. Quién puede hacerlo lo decide el servicio, no la vista."""
    leave_request = selectors.get_request_or_404(request.user, public_id=public_id)
    form = DecisionForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            services.cancel_request(
                leave_request=leave_request,
                actor=request.user,
                request=request,
                note=form.cleaned_data["note"],
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Leave request cancelled."))
            return redirect("leave:request_detail", public_id=leave_request.public_id)

    return render(
        request,
        "leave/request_decide.html",
        _decision_context(leave_request, form, decision="cancel"),
    )


def _decision_context(leave_request, form, *, decision: str) -> dict:
    """Contexto común: la pantalla dice **qué cambia** antes de decidir."""
    employee, leave_type = leave_request.employee, leave_request.leave_type
    return {
        "leave_request": leave_request,
        "form": form,
        "decision": decision,
        "balance": selectors.balance_for(employee, leave_type),
        "pending_days": selectors.pending_days_for(employee, leave_type, exclude=leave_request),
        "cancel_url": reverse("leave:request_detail", args=[leave_request.public_id]),
    }


# --------------------------------------------------------------------------- #
# Calendario de equipo
# --------------------------------------------------------------------------- #


@login_required
@permission_required("leave.view_leaverequest", raise_exception=True)
def team_calendar(request: HttpRequest) -> HttpResponse:
    raw_date = request.GET.get("from", "").strip()
    try:
        start = dt.date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        start = timezone.localdate()
    end = start + dt.timedelta(days=CALENDAR_DAYS - 1)

    days = [start + dt.timedelta(days=offset) for offset in range(CALENDAR_DAYS)]
    rows = [
        {
            "employee": row["employee"],
            "cells": [{"day": day, "entry": row["days"].get(day)} for day in days],
        }
        for row in selectors.team_calendar(request.user, start, end)
    ]
    return render(
        request,
        "leave/team_calendar.html",
        {
            "rows": rows,
            "days": days,
            "start": start,
            "end": end,
            "previous": start - dt.timedelta(days=CALENDAR_DAYS),
            "next": start + dt.timedelta(days=CALENDAR_DAYS),
        },
    )


# --------------------------------------------------------------------------- #
# Catálogo y saldos
# --------------------------------------------------------------------------- #


@login_required
@permission_required("leave.view_leavetype", raise_exception=True)
def type_list(request: HttpRequest) -> HttpResponse:
    types = selectors.types_visible_for(request.user).order_by("-is_active", "name")
    return render(request, "leave/type_list.html", {"types": types})


@login_required
@permission_required("leave.add_leavetype", raise_exception=True)
@require_http_methods(["GET", "POST"])
def type_create(request: HttpRequest) -> HttpResponse:
    form = LeaveTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.create_leave_type(actor=request.user, request=request, **form.cleaned_data)
        messages.success(request, _("Leave type created."))
        return redirect("leave:type_list")
    return render(request, "leave/type_form.html", {"form": form})


@login_required
@permission_required("leave.change_leavetype", raise_exception=True)
@require_http_methods(["GET", "POST"])
def type_update(request: HttpRequest, pk: int) -> HttpResponse:
    leave_type = get_object_or_404(selectors.types_visible_for(request.user), pk=pk)
    form = LeaveTypeForm(request.POST or None, instance=leave_type)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_leave_type(
                leave_type=leave_type, actor=request.user, request=request, **form.cleaned_data
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Leave type updated."))
            return redirect("leave:type_list")
    return render(
        request,
        "leave/type_form.html",
        {
            "form": form,
            "leave_type": leave_type,
            "tiers": leave_type.accrual_tiers.order_by("min_years_of_service"),
            "tier_form": AccrualTierForm(),
        },
    )


@login_required
@permission_required("leave.add_leaveaccrualtier", raise_exception=True)
@require_http_methods(["POST"])
def tier_add(request: HttpRequest, pk: int) -> HttpResponse:
    """Añade un tramo. El tipo sale de la URL validada, no del formulario."""
    leave_type = get_object_or_404(selectors.types_visible_for(request.user), pk=pk)
    form = AccrualTierForm(request.POST)
    if form.is_valid():
        try:
            services.add_accrual_tier(
                leave_type=leave_type,
                min_years_of_service=form.cleaned_data["min_years_of_service"],
                annual_days=form.cleaned_data["annual_days"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Seniority tier added."))
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("leave:type_update", pk=leave_type.pk)


@login_required
@permission_required("leave.delete_leaveaccrualtier", raise_exception=True)
@require_http_methods(["GET", "POST"])
def tier_remove(request: HttpRequest, pk: int, tier_pk: int) -> HttpResponse:
    leave_type = get_object_or_404(selectors.types_visible_for(request.user), pk=pk)
    tier = get_object_or_404(leave_type.accrual_tiers, pk=tier_pk)
    cancel_url = reverse("leave:type_update", args=[leave_type.pk])

    if request.method == "POST":
        services.remove_accrual_tier(tier=tier, actor=request.user, request=request)
        messages.success(request, _("Seniority tier removed."))
        return redirect(cancel_url)

    return render(
        request,
        "confirm_action.html",
        {
            "title": _("Remove seniority tier"),
            "subject": f"{leave_type.name} · ≥ {tier.min_years_of_service}",
            "consequences": [
                _("From the next accrual, that seniority receives the previous tier."),
                _("Days already accrued do not change: they are in the ledger."),
            ],
            "confirm_label": _("Remove tier"),
            "cancel_url": cancel_url,
            "danger": True,
        },
    )


@login_required
@permission_required("leave.add_leaveledgerentry", raise_exception=True)
@require_http_methods(["GET", "POST"])
def balance_adjust(request: HttpRequest) -> HttpResponse:
    """Corrección manual de saldo. Queda como asiento y como evento auditado."""
    form = BalanceAdjustmentForm(request.POST or None, user=request.user)

    if request.method == "POST" and form.is_valid():
        try:
            services.adjust_balance(
                employee=form.cleaned_data["employee"],
                leave_type=form.cleaned_data["leave_type"],
                days=form.cleaned_data["days"],
                note=form.cleaned_data["note"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Balance adjusted."))
            return redirect("leave:balance_adjust")

    return render(request, "leave/balance_adjust.html", {"form": form})


@login_required
@permission_required("leave.view_leaveledgerentry", raise_exception=True)
def employee_balance(request: HttpRequest, employee_code: str) -> HttpResponse:
    """Saldo y libro de una persona, dentro del alcance de quien consulta."""
    employee = employees_visible_for(request.user).filter(employee_code=employee_code).first()
    if employee is None:
        raise Http404
    return render(
        request,
        "leave/employee_balance.html",
        {
            "employee": employee,
            "balances": selectors.balances_for(employee),
            "page": Paginator(selectors.ledger_for(employee), 25).get_page(request.GET.get("page")),
        },
    )
