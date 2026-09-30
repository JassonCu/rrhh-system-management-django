"""Vistas de empleados.

Las tres capas en orden —autenticación, permiso, alcance— y **el identificador
de la URL es el `public_id`**, no la clave primaria: los empleados están en la
lista de entidades que no exponen identificadores enumerables (§B).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.contracts import selectors as contract_selectors
from apps.core.exceptions import ConflictError
from apps.documents import selectors as document_selectors
from apps.employees import selectors, services
from apps.employees.forms import (
    EmployeeForm,
    IdentityDocumentForm,
    PersonForm,
)

#: Pestañas de la ficha. El valor viaja en la URL: es estable y no se traduce.
EMPLOYEE_TABS = ("record", "documents", "file", "contracts")

#: Pestañas que muestran datos sensibles: solo esas registran el acceso (§K.5).
SENSITIVE_TABS = frozenset({"record", "documents"})

ERROR_MESSAGES = {
    "employee_below_minimum_age": _("The person is below the minimum working age."),
    "employee_already_terminated": _("That employee is already terminated."),
    "termination_before_hire": _("The termination date cannot precede the hire date."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


@login_required
@permission_required("employees.view_employee", raise_exception=True)
def employee_list(request: HttpRequest) -> HttpResponse:
    employees = selectors.employees_visible_for(request.user)

    query = request.GET.get("q", "").strip()
    if query:
        employees = employees.filter(
            Q(employee_code__icontains=query)
            | Q(person__first_name__icontains=query)
            | Q(person__last_name__icontains=query)
        )

    status = request.GET.get("status", "").strip()
    if status:
        employees = employees.filter(employment_status=status)

    page = Paginator(employees, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "employees/list.html",
        {"page": page, "query": query, "status": status},
    )


@login_required
@permission_required("employees.view_employee", raise_exception=True)
def employee_detail(request: HttpRequest, public_id) -> HttpResponse:
    employee = selectors.get_employee_or_404(request.user, public_id=public_id)
    show_sensitive = selectors.can_view_sensitive_pii(request.user, employee)
    is_own_record = employee.user_id is not None and employee.user_id == request.user.pk

    # Pestañas como enlaces (plan UX/UI §5): sin JavaScript y con URL propia.
    tab = request.GET.get("tab", "record")
    if tab not in EMPLOYEE_TABS:
        tab = "record"

    can_view_documents = request.user.has_perm("documents.view_employeedocument")
    file_documents = ()
    if tab == "file" and can_view_documents:
        # Cada fila dice si **esta** persona puede abrir el contenido: el
        # documento confidencial se ve que existe, pero no se descarga (§J.2).
        file_documents = [
            {
                "document": document,
                "can_open": document_selectors.can_open(request.user, document),
                "expiring": (document.days_to_expiry() or 0) >= 0 if document.expires_on else False,
            }
            for document in document_selectors.documents_for(request.user, employee)
        ]

    can_view_contracts = request.user.has_perm("contracts.view_employmentcontract")
    contracts = ()
    if tab == "contracts" and can_view_contracts:
        # Mismo selector con alcance que usa `contracts`: ver la ficha no abre
        # los contratos, los abre el permiso y el alcance (§J.4, sin cascada).
        contracts = contract_selectors.contracts_visible_for(request.user).filter(employee=employee)

    if show_sensitive and not is_own_record and tab in SENSITIVE_TABS:
        # No basta con controlar quién PUEDE verlos: hay que poder responder
        # quién los vio y cuándo (§K.5). Que alguien consulte su propia ficha no
        # se registra: llenaría la bitácora de ruido y diluiría la señal que
        # importa, que es el acceso de terceros.
        services.record_sensitive_access(employee=employee, actor=request.user, request=request)

    return render(
        request,
        "employees/detail.html",
        {
            "employee": employee,
            "person": employee.person,
            "documents": selectors.identity_documents_for(request.user, employee),
            "contacts": selectors.contact_methods_for(request.user, employee),
            "emergency_contacts": selectors.emergency_contacts_for(request.user, employee),
            "show_sensitive": show_sensitive,
            "show_personal": selectors.can_view_personal_data(request.user, employee),
            "tab": tab,
            "contracts": contracts,
            "can_view_contracts": can_view_contracts,
            "can_view_documents": can_view_documents,
            "file_documents": file_documents,
            "can_upload_documents": (
                request.user.has_perm("documents.add_employeedocument")
                and document_selectors.uploadable_types_for(request.user, employee).exists()
            ),
        },
    )


@login_required
@permission_required("employees.add_employee", raise_exception=True)
@require_http_methods(["GET", "POST"])
def employee_create(request: HttpRequest) -> HttpResponse:
    person_form = PersonForm(request.POST or None, prefix="person")
    employee_form = EmployeeForm(request.POST or None, prefix="employee")

    if request.method == "POST" and person_form.is_valid() and employee_form.is_valid():
        try:
            employee = services.create_employee(
                actor=request.user,
                request=request,
                person_data=person_form.cleaned_data,
                employee_code=employee_form.cleaned_data["employee_code"],
                hire_date=employee_form.cleaned_data["hire_date"],
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Employee created."))
            return redirect("employees:detail", public_id=employee.public_id)

    return render(
        request,
        "employees/form.html",
        {"person_form": person_form, "employee_form": employee_form},
    )


@login_required
@permission_required("employees.change_employee", raise_exception=True)
@require_http_methods(["GET", "POST"])
def employee_update(request: HttpRequest, public_id) -> HttpResponse:
    employee = selectors.get_employee_or_404(request.user, public_id=public_id)
    person_form = PersonForm(request.POST or None, instance=employee.person, prefix="person")

    if request.method == "POST" and person_form.is_valid():
        services.update_person(
            person=employee.person,
            actor=request.user,
            request=request,
            **person_form.cleaned_data,
        )
        messages.success(request, _("Employee updated."))
        return redirect("employees:detail", public_id=employee.public_id)

    return render(
        request,
        "employees/form.html",
        {"person_form": person_form, "employee": employee},
    )


@login_required
@permission_required("employees.change_employee", raise_exception=True)
@require_http_methods(["GET", "POST"])
def document_add(request: HttpRequest, public_id) -> HttpResponse:
    employee = selectors.get_employee_or_404(request.user, public_id=public_id)
    form = IdentityDocumentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        services.add_identity_document(
            person=employee.person, actor=request.user, request=request, **form.cleaned_data
        )
        messages.success(request, _("Document added."))
        return redirect("employees:detail", public_id=employee.public_id)

    return render(request, "employees/document_form.html", {"form": form, "employee": employee})
