"""Vistas de la relación laboral.

Tres capas en cada vista: autenticación, permiso y alcance. Los contratos se
direccionan por `public_id`; las asignaciones, por su clave **dentro** de un
contrato ya autorizado, nunca sueltas.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.contracts import selectors, services
from apps.contracts.constants import ALLOWED_TRANSITIONS, ContractStatus
from apps.contracts.forms import (
    AssignmentForm,
    ContractForm,
    EndAssignmentForm,
    SalaryForm,
    TerminateContractForm,
)
from apps.core.exceptions import ConflictError
from apps.employees.selectors import get_employee_or_404
from apps.positions.selectors import job_grades_visible_for

#: Los servicios devuelven códigos estables; aquí se traducen (§O.5.1).
ERROR_MESSAGES = {
    "invalid_contract_transition": _("That status change is not allowed."),
    "contract_needs_salary": _("Register the initial salary, starting on the contract start date."),
    "contract_needs_primary_assignment": _("The contract needs a current primary position."),
    "employee_has_live_contract": _("The employee already has a live contract."),
    "contract_overlap": _("The contract overlaps another contract of the same employee."),
    "contract_is_closed": _("The contract is closed and cannot be changed."),
    "salary_outside_contract": _("The salary date is outside the contract."),
    "first_salary_must_start_with_contract": _(
        "The first salary must start on the contract start date."
    ),
    "salary_not_after_previous": _("A new salary must start after the current one."),
    "salary_out_of_band_requires_justification": _(
        "The amount is outside the salary band of the position: add a justification."
    ),
    "salary_below_legal_minimum": _("The amount is below the legal minimum wage."),
    "assignment_outside_contract": _("The assignment date is outside the contract."),
    "position_inactive": _("That position is inactive."),
    "assignment_not_after_previous_primary": _(
        "A new primary position must start after the current one."
    ),
    "fte_exceeds_full_time": _("The assignments would exceed full time."),
    "assignment_already_ended": _("That assignment has already ended."),
    "assignment_end_before_start": _("The end date cannot precede the start date."),
    "invalid_termination_reason": _("Choose a valid termination reason."),
    "termination_before_start": _("The termination date cannot precede the contract start."),
    "termination_after_contract_end": _("The termination date is after the contract end."),
    "salary_starts_after_termination": _("There is a salary change scheduled after that date."),
    "assignment_starts_after_termination": _("There is an assignment scheduled after that date."),
    "cannot_deactivate_self": _("You cannot terminate your own employment."),
    "cannot_change_own_employment": _("You cannot change your own employment."),
    "termination_in_future": _("The termination date cannot be in the future."),
    "position_in_another_company": _("The position belongs to another company."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


@login_required
@permission_required("contracts.view_employmentcontract", raise_exception=True)
def contract_list(request: HttpRequest) -> HttpResponse:
    contracts = selectors.contracts_visible_for(request.user)

    employee_filter = request.GET.get("employee", "").strip()
    if employee_filter:
        try:
            contracts = contracts.filter(employee__public_id=uuid.UUID(employee_filter))
        except ValueError:
            contracts = contracts.none()  # un filtro mal formado no amplía nada

    status = request.GET.get("status", "").strip()
    if status in ContractStatus.values:
        contracts = contracts.filter(status=status)

    page = Paginator(contracts, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "contracts/list.html",
        {"page": page, "status": status, "employee_filter": employee_filter},
    )


@login_required
@permission_required("contracts.view_employmentcontract", raise_exception=True)
def contract_detail(request: HttpRequest, public_id) -> HttpResponse:
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    allowed = ALLOWED_TRANSITIONS[contract.status]
    can_view_salary = selectors.can_view_salary(request.user, contract)
    if can_view_salary and contract.employee.user_id != request.user.pk:
        # Solo terceros: consultar el propio salario no aporta señal (Fase 3, H-2).
        services.record_salary_access(contract=contract, actor=request.user, request=request)
    return render(
        request,
        "contracts/detail.html",
        {
            "contract": contract,
            "salaries": selectors.salaries_for(request.user, contract),
            "can_view_salary": can_view_salary,
            "assignments": selectors.assignments_for(request.user, contract),
            "can_activate": contract.status == ContractStatus.DRAFT,
            "can_suspend": ContractStatus.SUSPENDED.value in allowed,
            "can_resume": contract.status == ContractStatus.SUSPENDED,
            "can_terminate": ContractStatus.TERMINATED.value in allowed,
            "is_editable": contract.status
            not in {ContractStatus.TERMINATED, ContractStatus.EXPIRED},
        },
    )


@login_required
@permission_required("contracts.add_employmentcontract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_create(request: HttpRequest, employee_public_id) -> HttpResponse:
    # El titular sale de la URL **validada por el selector**, no del formulario.
    employee = get_employee_or_404(request.user, public_id=employee_public_id)
    form = ContractForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contract = services.create_contract(
            employee=employee, actor=request.user, request=request, **form.cleaned_data
        )
        messages.success(request, _("Draft contract created."))
        # El alta entra directo al asistente: contratar es un flujo, no una ficha.
        return redirect("contracts:wizard", public_id=contract.public_id)
    return render(
        request,
        "contracts/form.html",
        {"form": form, "title": _("New contract"), "subject": employee},
    )


@login_required
@permission_required("contracts.change_salary", raise_exception=True)
@require_http_methods(["GET", "POST"])
def salary_set(request: HttpRequest, public_id) -> HttpResponse:
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    form = SalaryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.set_salary(
                contract=contract, actor=request.user, request=request, **form.cleaned_data
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Salary registered."))
            return redirect("contracts:detail", public_id=contract.public_id)
    return render(
        request,
        "contracts/form.html",
        {"form": form, "title": _("Register salary"), "contract": contract},
    )


@login_required
@permission_required("contracts.add_assignment", raise_exception=True)
@require_http_methods(["GET", "POST"])
def assignment_add(request: HttpRequest, public_id) -> HttpResponse:
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    form = AssignmentForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.add_assignment(
                contract=contract, actor=request.user, request=request, **form.cleaned_data
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Position assigned."))
            return redirect("contracts:detail", public_id=contract.public_id)
    return render(
        request,
        "contracts/form.html",
        {"form": form, "title": _("Assign position"), "contract": contract},
    )


@login_required
@permission_required("contracts.change_assignment", raise_exception=True)
@require_http_methods(["POST"])
def assignment_end(request: HttpRequest, public_id, pk: int) -> HttpResponse:
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    # La asignación se busca DENTRO del contrato autorizado: una clave de otra
    # persona en la URL da 404, no acceso (IDOR).
    assignment = get_object_or_404(selectors.assignments_for(request.user, contract), pk=pk)
    form = EndAssignmentForm(request.POST)
    if form.is_valid():
        try:
            services.end_assignment(
                assignment=assignment,
                end_date=form.cleaned_data["end_date"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Assignment ended."))
    else:
        messages.error(request, _("Enter a valid end date."))
    return redirect("contracts:detail", public_id=contract.public_id)


#: Orden de los pasos del asistente y su etiqueta.
WIZARD_STEPS = ("position", "salary", "review")

#: Permiso que exige cada paso. El del contrato ya lo comprueba el decorador.
WIZARD_PERMISSIONS = {
    "position": "contracts.add_assignment",
    "salary": "contracts.change_salary",
}


def _wizard_step(assignment, salary) -> str:
    """El paso se deduce del estado del contrato, no de la sesión.

    Así el asistente se puede abandonar y retomar, y dos pestañas abiertas no se
    contradicen.
    """
    if assignment is None:
        return "position"
    if salary is None:
        return "salary"
    return "review"


def _wizard_progress(step: str) -> list[dict[str, str]]:
    labels = {
        "position": _("Position"),
        "salary": _("Salary"),
        "review": _("Review and activate"),
    }
    current = WIZARD_STEPS.index(step)
    states = ["done"] * current + ["current"] + ["pending"] * (len(WIZARD_STEPS) - current - 1)
    return [
        {"label": labels[name], "state": state}
        for name, state in zip(WIZARD_STEPS, states, strict=True)
    ]


@login_required
@permission_required("contracts.change_employmentcontract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_wizard(request: HttpRequest, public_id) -> HttpResponse:
    """Asistente de contratación: puesto → salario → revisar y activar.

    El puesto va **antes** que el salario para poder mostrar la banda del grado
    antes de guardar, en lugar de rechazar el importe después (RN-23).
    """
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    assignment = selectors.current_primary_assignment(contract, contract.start_date)
    salary = contract.salaries.order_by("-effective_from").first()
    step = _wizard_step(assignment, salary)

    needed = WIZARD_PERMISSIONS.get(step)
    if needed and not request.user.has_perm(needed):
        raise PermissionDenied

    form = None
    if step == "position":
        form = AssignmentForm(
            request.POST or None, user=request.user, initial={"start_date": contract.start_date}
        )
    elif step == "salary":
        form = SalaryForm(request.POST or None, initial={"effective_from": contract.start_date})

    if request.method == "POST" and form is not None and form.is_valid():
        try:
            if step == "position":
                services.add_assignment(
                    contract=contract, actor=request.user, request=request, **form.cleaned_data
                )
            else:
                services.set_salary(
                    contract=contract, actor=request.user, request=request, **form.cleaned_data
                )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            return redirect("contracts:wizard", public_id=contract.public_id)

    band = None
    if assignment is not None:
        # La banda es confidencial: solo se muestra a quien puede ver grados (§J.4).
        band = (
            job_grades_visible_for(request.user).filter(pk=assignment.position.job_grade_id).first()
        )

    return render(
        request,
        "contracts/wizard.html",
        {
            "contract": contract,
            "step": step,
            "steps": _wizard_progress(step),
            "form": form,
            "assignment": assignment,
            "salary": salary,
            "band": band,
            "can_view_salary": selectors.can_view_salary(request.user, contract),
        },
    )


def _transition_view(
    request, public_id, *, service, success_message, title, consequences, danger=False
):
    """Cambio de estado con confirmación previa (plan UX/UI §5).

    El `GET` solo muestra las consecuencias; el cambio ocurre con `POST` y CSRF,
    así que un enlace no puede dispararlo.
    """
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)

    if request.method == "GET":
        employee = contract.employee
        return render(
            request,
            "confirm_action.html",
            {
                "title": title,
                "subject": f"{employee.person.full_name} · {employee.employee_code}",
                "consequences": consequences,
                "confirm_label": title,
                "cancel_url": reverse("contracts:detail", args=[contract.public_id]),
                "danger": danger,
            },
        )

    try:
        service(contract=contract, actor=request.user, request=request)
    except ConflictError as error:
        messages.error(request, _message_for(error))
    else:
        messages.success(request, success_message)
    return redirect("contracts:detail", public_id=contract.public_id)


@login_required
@permission_required("contracts.change_employmentcontract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_activate(request: HttpRequest, public_id) -> HttpResponse:
    return _transition_view(
        request,
        public_id,
        service=services.activate_contract,
        success_message=_("Contract activated."),
        title=_("Activate contract"),
        consequences=[
            _("The contract will move to Active."),
            _("The person will appear as active and in their manager's team."),
            _("It requires an initial salary and a current primary position."),
        ],
    )


@login_required
@permission_required("contracts.change_employmentcontract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_suspend(request: HttpRequest, public_id) -> HttpResponse:
    return _transition_view(
        request,
        public_id,
        service=services.suspend_contract,
        success_message=_("Contract suspended."),
        title=_("Suspend contract"),
        consequences=[
            _("The contract will move to Suspended."),
            _("The person remains employed: their salary and positions stay open."),
            _("Their employment status will show as suspended across the system."),
        ],
        danger=True,
    )


@login_required
@permission_required("contracts.change_employmentcontract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_resume(request: HttpRequest, public_id) -> HttpResponse:
    return _transition_view(
        request,
        public_id,
        service=services.resume_contract,
        success_message=_("Contract resumed."),
        title=_("Resume contract"),
        consequences=[
            _("The contract will move back to Active."),
            _("The person will appear as active again."),
        ],
    )


@login_required
@permission_required("contracts.terminate_contract", raise_exception=True)
@require_http_methods(["GET", "POST"])
def contract_terminate(request: HttpRequest, public_id) -> HttpResponse:
    contract = selectors.get_contract_or_404(request.user, public_id=public_id)
    form = TerminateContractForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.terminate_contract(
                contract=contract,
                termination_date=form.cleaned_data["termination_date"],
                reason=form.cleaned_data["termination_reason"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Contract terminated."))
            return redirect("contracts:detail", public_id=contract.public_id)
    return render(request, "contracts/terminate.html", {"form": form, "contract": contract})
