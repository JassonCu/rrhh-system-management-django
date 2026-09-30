"""Vistas de la estructura organizacional."""

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
from apps.departments import selectors, services
from apps.departments.forms import CompanyForm, DepartmentForm, EndHeadshipForm, HeadshipForm

ERROR_MESSAGES = {
    "department_cycle": _("That parent would make the department its own ancestor."),
    "department_is_its_own_parent": _("A department cannot be its own parent."),
    "department_parent_in_another_company": _("The parent must belong to the same company."),
    "department_has_active_children": _("Deactivate its sub-departments first."),
    "department_has_active_positions": _("Deactivate its positions first."),
    "already_head": _("That person already heads this department."),
    "headship_not_after_previous": _("The new appointment must start after the current one."),
    "headship_already_ended": _("That headship has already ended."),
    "headship_end_before_start": _("The end date cannot precede the start date."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


@login_required
@permission_required("departments.view_department", raise_exception=True)
def department_list(request: HttpRequest) -> HttpResponse:
    departments = selectors.departments_visible_for(request.user)
    query = request.GET.get("q", "").strip()
    if query:
        departments = departments.filter(name__icontains=query)

    page = Paginator(departments, 25).get_page(request.GET.get("page"))
    return render(request, "departments/list.html", {"page": page, "query": query})


@login_required
@permission_required("departments.view_department", raise_exception=True)
def department_detail(request: HttpRequest, pk: int) -> HttpResponse:
    department = get_object_or_404(selectors.departments_visible_for(request.user), pk=pk)
    return render(
        request,
        "departments/detail.html",
        {
            "department": department,
            "ancestors": list(reversed(department.ancestors())),
            "children": department.children.filter(is_active=True),
            "headships": selectors.headships_for(department),
            "current_head": selectors.current_head(department),
        },
    )


@login_required
@permission_required("departments.add_department", raise_exception=True)
@require_http_methods(["GET", "POST"])
def department_create(request: HttpRequest) -> HttpResponse:
    form = DepartmentForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            department = services.create_department(
                actor=request.user, request=request, **form.cleaned_data
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Department created."))
            return redirect("departments:detail", pk=department.pk)
    return render(request, "departments/form.html", {"form": form})


@login_required
@permission_required("departments.change_department", raise_exception=True)
@require_http_methods(["GET", "POST"])
def department_update(request: HttpRequest, pk: int) -> HttpResponse:
    department = get_object_or_404(selectors.departments_visible_for(request.user), pk=pk)
    form = DepartmentForm(request.POST or None, instance=department, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_department(
                department=department, actor=request.user, request=request, **form.cleaned_data
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Department updated."))
            return redirect("departments:detail", pk=department.pk)
    return render(request, "departments/form.html", {"form": form, "department": department})


@login_required
@permission_required("departments.change_department", raise_exception=True)
@require_http_methods(["GET", "POST"])
def department_deactivate(request: HttpRequest, pk: int) -> HttpResponse:
    """El `GET` muestra la confirmación; la baja se ejecuta con `POST` y CSRF."""
    department = get_object_or_404(selectors.departments_visible_for(request.user), pk=pk)

    if request.method == "GET":
        return render(
            request,
            "confirm_action.html",
            {
                "title": _("Deactivate department"),
                "subject": f"{department.code} · {department.name}",
                "consequences": [
                    _("The department will no longer be available for new positions."),
                    _("It is not deleted: the history refers to it."),
                    _("It only works if it has no active sub-departments or positions."),
                ],
                "confirm_label": _("Deactivate department"),
                "cancel_url": reverse("departments:detail", args=[department.pk]),
                "danger": True,
            },
        )

    try:
        services.deactivate_department(department=department, actor=request.user, request=request)
    except ConflictError as error:
        messages.error(request, _message_for(error))
    else:
        messages.success(request, _("Department deactivated."))
    return redirect("departments:detail", pk=department.pk)


# --------------------------------------------------------------------------- #
# Empresas y jefaturas fuera del admin (UX-3, D-07)
# --------------------------------------------------------------------------- #


@login_required
@permission_required("core.view_company", raise_exception=True)
def company_list(request: HttpRequest) -> HttpResponse:
    companies = selectors.companies_visible_for(request.user)
    page = Paginator(companies, 25).get_page(request.GET.get("page"))
    return render(request, "departments/company_list.html", {"page": page})


@login_required
@permission_required("core.add_company", raise_exception=True)
@require_http_methods(["GET", "POST"])
def company_create(request: HttpRequest) -> HttpResponse:
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.create_company(actor=request.user, request=request, **form.cleaned_data)
        messages.success(request, _("Company created."))
        return redirect("departments:company_list")
    return render(request, "departments/company_form.html", {"form": form})


@login_required
@permission_required("core.change_company", raise_exception=True)
@require_http_methods(["GET", "POST"])
def company_update(request: HttpRequest, pk: int) -> HttpResponse:
    company = get_object_or_404(selectors.companies_visible_for(request.user), pk=pk)
    form = CompanyForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        services.update_company(
            company=company, actor=request.user, request=request, **form.cleaned_data
        )
        messages.success(request, _("Company updated."))
        return redirect("departments:company_list")
    return render(request, "departments/company_form.html", {"form": form, "company": company})


@login_required
@permission_required("departments.add_departmentheadship", raise_exception=True)
@require_http_methods(["GET", "POST"])
def headship_assign(request: HttpRequest, pk: int) -> HttpResponse:
    department = get_object_or_404(selectors.departments_visible_for(request.user), pk=pk)
    form = HeadshipForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.assign_head(
                department=department,
                actor=request.user,
                request=request,
                **form.cleaned_data,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Department head appointed."))
            return redirect("departments:detail", pk=department.pk)
    return render(
        request,
        "departments/headship_form.html",
        {"form": form, "department": department, "current": selectors.current_head(department)},
    )


@login_required
@permission_required("departments.change_departmentheadship", raise_exception=True)
@require_http_methods(["GET", "POST"])
def headship_end(request: HttpRequest, pk: int, headship_pk: int) -> HttpResponse:
    """El `GET` muestra la confirmación; la jefatura se cierra con `POST` y CSRF."""
    department = get_object_or_404(selectors.departments_visible_for(request.user), pk=pk)
    # La jefatura se busca DENTRO del departamento autorizado, nunca suelta.
    headship = get_object_or_404(selectors.headships_for(department), pk=headship_pk)
    form = EndHeadshipForm(request.POST or None)

    if request.method == "GET":
        return render(
            request,
            "confirm_action.html",
            {
                "title": _("End headship"),
                "subject": f"{department.code} · {headship.employee.person.full_name}",
                "consequences": [
                    _("The department will have no head until a new appointment."),
                    _("The history is kept: it records who was in charge and when."),
                    _("Their team will stop appearing in their scope."),
                ],
                "confirm_label": _("End headship"),
                "cancel_url": reverse("departments:detail", args=[department.pk]),
                "danger": True,
                "form": form,
            },
        )

    if form.is_valid():
        try:
            services.end_headship(
                headship=headship,
                end_date=form.cleaned_data["end_date"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Headship ended."))
    else:
        messages.error(request, _("Enter a valid end date."))
    return redirect("departments:detail", pk=department.pk)
