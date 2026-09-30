"""Consultas de lectura sobre la estructura organizacional (ADR-005)."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.core.models import Company
from apps.departments.models import Department, DepartmentHeadship

#: Tope de profundidad al expandir el árbol. El organigrama esperado tiene ≤ 5
#: niveles; el límite impide que una corrupción de datos convierta una consulta
#: en un bucle infinito.
MAX_DEPTH = 20


def departments_visible_for(user) -> QuerySet[Department]:
    """Departamentos que este usuario puede ver.

    El organigrama es información interna no sensible: cualquier usuario
    autenticado lo consulta (§J.2). Lo que **no** es público es quién trabaja en
    cada área, que se resolverá con `employees_visible_for`.
    """
    if not user.is_authenticated:
        return Department.objects.none()
    return Department.objects.select_related("company", "parent")


def descendant_ids(department_ids: list[int] | set[int]) -> set[int]:
    """IDs del subárbol completo, incluidos los de partida.

    Es la base del alcance de un `MANAGER`: jefear un departamento implica ver
    también sus dependencias. Se expande por niveles con un tope explícito en
    lugar de recursión, para no depender de CTE (que SQLite y PostgreSQL
    expresan distinto) ni arriesgar un bucle.
    """
    collected = set(department_ids)
    frontier = set(collected)
    for _depth in range(MAX_DEPTH):
        if not frontier:
            break
        children = set(
            Department.objects.filter(parent_id__in=frontier)
            .exclude(pk__in=collected)
            .values_list("pk", flat=True)
        )
        collected |= children
        frontier = children
    return collected


def would_create_a_cycle(*, department: Department, new_parent: Department | None) -> bool:
    """Si asignar `new_parent` haría que el departamento fuera su propio ancestro."""
    if new_parent is None:
        return False
    if new_parent.pk == department.pk:
        return True
    return new_parent.pk in descendant_ids([department.pk])


def departments_headed_by(user) -> set[int]:
    """IDs de los departamentos que el usuario jefea **hoy**, con su subárbol.

    Es la base del alcance del rol `MANAGER`. Devuelve el conjunto vacío si el
    usuario no está vinculado a un empleado: una cuenta sin empleado no jefea
    nada, por mucho rol que tenga.
    """
    employee = getattr(user, "employee", None)
    if employee is None:
        return set()

    headed = set(
        DepartmentHeadship.objects.filter(employee=employee, end_date__isnull=True).values_list(
            "department_id", flat=True
        )
    )
    return descendant_ids(headed) if headed else set()


def companies_visible_for(user) -> QuerySet[Company]:
    """Empresas que este usuario puede ver.

    La empresa es un dato de organización, no personal: quien tiene el permiso
    las ve todas. El alcance por departamento no aplica aquí.
    """
    if not user.is_authenticated or not user.has_perm("core.view_company"):
        return Company.objects.none()
    return Company.objects.all()


def headships_for(department: Department) -> QuerySet[DepartmentHeadship]:
    """Historial de jefaturas de un departamento, la vigente primero."""
    return department.headships.select_related("employee__person").order_by("-start_date", "-id")


def current_head(department: Department) -> DepartmentHeadship | None:
    return (
        department.headships.select_related("employee__person")
        .filter(end_date__isnull=True)
        .first()
    )
