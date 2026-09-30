"""Casos de uso de la estructura organizacional.

Aquí viven las invariantes que la base no puede expresar de forma portable
(§E.4): la aciclicidad del organigrama y las condiciones de desactivación.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.http import HttpRequest

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.core.exceptions import ConflictError
from apps.core.models import Company
from apps.departments.models import Department, DepartmentHeadship
from apps.departments.selectors import would_create_a_cycle

ONE_DAY = dt.timedelta(days=1)


@transaction.atomic
def create_department(*, actor, request: HttpRequest, **fields) -> Department:
    department = Department(**fields)
    _validate_hierarchy(department, department.parent)
    department.full_clean()
    department.save()

    record(
        action=AuditAction.DEPARTMENT_CREATE,
        actor=actor,
        obj=department,
        request=request,
        metadata={"code": department.code, "parent": str(department.parent or "")},
    )
    return department


@transaction.atomic
def update_department(
    *, department: Department, actor, request: HttpRequest, **fields
) -> Department:
    previous = {
        "name": department.name,
        "parent": str(department.parent or ""),
        "cost_center": department.cost_center,
    }
    for key, value in fields.items():
        setattr(department, key, value)

    _validate_hierarchy(department, department.parent)
    department.full_clean()
    department.save()

    record(
        action=AuditAction.DEPARTMENT_UPDATE,
        actor=actor,
        obj=department,
        request=request,
        metadata={"from": previous, "to": {k: str(v) for k, v in fields.items()}},
    )
    return department


@transaction.atomic
def deactivate_department(*, department: Department, actor, request: HttpRequest) -> Department:
    """Baja lógica. **Nunca se borra**: el histórico lo referencia (RN-33).

    Exige que no queden subdepartamentos ni puestos activos. Con eso basta para
    que ninguna asignación vigente apunte al departamento: un puesto ocupado no
    puede desactivarse (`deactivate_position`), así que sigue activo y bloquea
    esta baja.
    """
    active_children = department.children.filter(is_active=True).count()
    if active_children:
        raise ConflictError("department_has_active_children", count=active_children)

    active_positions = department.positions.filter(is_active=True).count()
    if active_positions:
        raise ConflictError("department_has_active_positions", count=active_positions)

    department.is_active = False
    department.save(update_fields=["is_active", "updated_at"])

    record(
        action=AuditAction.DEPARTMENT_DEACTIVATE,
        actor=actor,
        obj=department,
        request=request,
    )
    return department


def _validate_hierarchy(department: Department, new_parent: Department | None) -> None:
    """RN-31: el organigrama es acíclico.

    No es expresable como `CheckConstraint` sin un trigger recursivo, ni en
    SQLite ni en PostgreSQL, así que se aplica aquí y se prueba en todas sus
    formas: padre igual a sí mismo, ciclo directo y ciclo indirecto.
    """
    if new_parent is None:
        return
    if department.pk and would_create_a_cycle(department=department, new_parent=new_parent):
        raise ConflictError(
            "department_cycle",
            department=str(department),
            parent=str(new_parent),
        )
    if department.pk and new_parent.pk == department.pk:
        raise ConflictError("department_is_its_own_parent", department=str(department))
    if new_parent.company_id != department.company_id:
        raise ConflictError("department_parent_in_another_company")


# --------------------------------------------------------------------------- #
# Empresa y jefaturas: salen del admin de Django en la entrega UX-3.
#
# Viven en `departments` porque son la estructura de la organización: la empresa
# es la raíz del organigrama y la jefatura, su vínculo con las personas. `core`
# no puede alojarlas: no depende de ningún dominio y no podría auditar (ADR-001).
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_company(*, actor, request: HttpRequest | None, **fields) -> Company:
    company = Company(**fields)
    company.full_clean()
    company.save()

    record(
        action=AuditAction.COMPANY_CREATE,
        actor=actor,
        obj=company,
        request=request,
        metadata={"code": company.code, "legal_name": company.legal_name},
    )
    return company


@transaction.atomic
def update_company(*, company: Company, actor, request: HttpRequest | None, **fields) -> Company:
    # Se compara contra la fila de la base: si viene de un ModelForm, la instancia
    # que llega ya trae los valores nuevos y el diff saldría vacío.
    stored = Company.objects.get(pk=company.pk)
    changed = sorted(name for name, value in fields.items() if getattr(stored, name) != value)
    for name, value in fields.items():
        setattr(company, name, value)
    company.full_clean()
    company.save()

    record(
        action=AuditAction.COMPANY_UPDATE,
        actor=actor,
        obj=company,
        request=request,
        metadata={"code": company.code, "changed": changed},
    )
    return company


@transaction.atomic
def assign_head(
    *,
    department: Department,
    employee,
    start_date: dt.date,
    actor,
    request: HttpRequest | None,
    appointment_note: str = "",
) -> DepartmentHeadship:
    """Nombra jefatura y cierra la anterior el día previo.

    No se sobrescribe la jefatura vigente: la pregunta que el sistema debe poder
    responder es quién mandaba **el día** que se aprobó algo (ADR-014).
    """
    current = (
        DepartmentHeadship.objects.select_for_update()
        .filter(department=department, end_date__isnull=True)
        .first()
    )
    if current is not None:
        if current.employee_id == employee.pk:
            raise ConflictError("already_head", employee=employee.employee_code)
        if start_date <= current.start_date:
            raise ConflictError("headship_not_after_previous")
        current.end_date = start_date - ONE_DAY
        current.save(update_fields=["end_date", "updated_at"])

    headship = DepartmentHeadship(
        department=department,
        employee=employee,
        start_date=start_date,
        appointment_note=appointment_note,
    )
    headship.full_clean()
    headship.save()

    record(
        action=AuditAction.HEADSHIP_ASSIGN,
        actor=actor,
        obj=headship,
        request=request,
        metadata={
            "department": department.code,
            "employee_code": employee.employee_code,
            "start_date": start_date.isoformat(),
        },
    )
    return headship


@transaction.atomic
def end_headship(
    *, headship: DepartmentHeadship, end_date: dt.date, actor, request: HttpRequest | None
) -> DepartmentHeadship:
    """Cierra una jefatura. El departamento queda sin jefe hasta el próximo nombramiento."""
    headship = DepartmentHeadship.objects.select_for_update().get(pk=headship.pk)
    if headship.end_date is not None:
        raise ConflictError("headship_already_ended")
    if end_date < headship.start_date:
        raise ConflictError("headship_end_before_start")

    headship.end_date = end_date
    headship.save(update_fields=["end_date", "updated_at"])

    record(
        action=AuditAction.HEADSHIP_END,
        actor=actor,
        obj=headship,
        request=request,
        metadata={
            "department": headship.department.code,
            "employee_code": headship.employee.employee_code,
            "end_date": end_date.isoformat(),
        },
    )
    return headship
