"""Vistas del catálogo de puestos y bandas salariales."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import ConflictError
from apps.positions import selectors, services
from apps.positions.forms import JobGradeForm, PositionForm


@login_required
@permission_required("positions.view_position", raise_exception=True)
def position_list(request: HttpRequest) -> HttpResponse:
    positions = selectors.positions_visible_for(request.user)
    query = request.GET.get("q", "").strip()
    if query:
        positions = positions.filter(title__icontains=query)

    page = Paginator(positions, 25).get_page(request.GET.get("page"))
    return render(request, "positions/list.html", {"page": page, "query": query})


@login_required
@permission_required("positions.view_position", raise_exception=True)
def position_detail(request: HttpRequest, pk: int) -> HttpResponse:
    position = get_object_or_404(selectors.positions_visible_for(request.user), pk=pk)
    # La banda salarial es confidencial: se resuelve con su propio selector, no
    # heredando el acceso al puesto (§J.4, "sin cascada de permisos").
    grade = selectors.job_grades_visible_for(request.user).filter(pk=position.job_grade_id).first()
    return render(request, "positions/detail.html", {"position": position, "grade": grade})


@login_required
@permission_required("positions.add_position", raise_exception=True)
@require_http_methods(["GET", "POST"])
def position_create(request: HttpRequest) -> HttpResponse:
    form = PositionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        position = services.create_position(
            actor=request.user, request=request, **form.cleaned_data
        )
        messages.success(request, _("Position created."))
        return redirect("positions:detail", pk=position.pk)
    return render(request, "positions/form.html", {"form": form})


@login_required
@permission_required("positions.change_position", raise_exception=True)
@require_http_methods(["GET", "POST"])
def position_update(request: HttpRequest, pk: int) -> HttpResponse:
    position = get_object_or_404(selectors.positions_visible_for(request.user), pk=pk)
    form = PositionForm(request.POST or None, instance=position, user=request.user)
    if request.method == "POST" and form.is_valid():
        services.update_position(
            position=position, actor=request.user, request=request, **form.cleaned_data
        )
        messages.success(request, _("Position updated."))
        return redirect("positions:detail", pk=position.pk)
    return render(request, "positions/form.html", {"form": form, "position": position})


@login_required
@permission_required("positions.change_position", raise_exception=True)
@require_http_methods(["GET", "POST"])
def position_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """El `GET` muestra la confirmación; la baja se ejecuta con `POST` y CSRF."""
    position = get_object_or_404(selectors.positions_visible_for(request.user), pk=pk)

    if request.method == "GET":
        return render(
            request,
            "confirm_action.html",
            {
                "title": _("Deactivate position"),
                "subject": f"{position.code} · {position.title}",
                "consequences": [
                    _("The position can no longer be assigned in a contract."),
                    _("It is not deleted: the history refers to it."),
                    _("It only works if it has no current or scheduled assignments."),
                ],
                "confirm_label": _("Deactivate position"),
                "cancel_url": reverse("positions:detail", args=[position.pk]),
                "danger": True,
            },
        )

    try:
        services.deactivate_position(position=position, actor=request.user, request=request)
    except ConflictError:
        messages.error(request, _("The position has current assignments."))
    else:
        messages.success(request, _("Position deactivated."))
    return redirect("positions:detail", pk=position.pk)


@login_required
@permission_required("positions.view_jobgrade", raise_exception=True)
def job_grade_list(request: HttpRequest) -> HttpResponse:
    """Bandas salariales. **Confidencial**: ni MANAGER ni HR_MANAGER las ven."""
    grades = selectors.job_grades_visible_for(request.user)
    page = Paginator(grades, 25).get_page(request.GET.get("page"))
    return render(request, "positions/job_grade_list.html", {"page": page})


@login_required
@permission_required("positions.add_jobgrade", raise_exception=True)
@require_http_methods(["GET", "POST"])
def job_grade_create(request: HttpRequest) -> HttpResponse:
    form = JobGradeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.create_job_grade(actor=request.user, request=request, **form.cleaned_data)
        messages.success(request, _("Job grade created."))
        return redirect("positions:job_grade_list")
    return render(request, "positions/job_grade_form.html", {"form": form})
