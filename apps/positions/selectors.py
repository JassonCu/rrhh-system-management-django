"""Consultas de lectura sobre el catálogo de puestos (ADR-005)."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.positions.models import JobGrade, Position


def positions_visible_for(user) -> QuerySet[Position]:
    """Puestos que este usuario puede ver.

    Según la matriz §J.2, el catálogo de puestos lo consultan RRHH y auditoría.
    `MANAGER` y `EMPLOYEE` **no** lo ven: el permiso lo decide, y aquí solo se
    evita devolver datos a quien llegue sin él.
    """
    if not user.is_authenticated or not user.has_perm("positions.view_position"):
        return Position.objects.none()
    return Position.objects.select_related("department", "job_grade")


def job_grades_visible_for(user) -> QuerySet[JobGrade]:
    """Bandas salariales: información **confidencial**.

    `HR_MANAGER` ve los puestos pero no sus bandas; es el "T (sin banda)" de la
    matriz. Por eso el alcance de esta entidad es distinto del de `Position`.
    """
    if not user.is_authenticated or not user.has_perm("positions.view_jobgrade"):
        return JobGrade.objects.none()
    return JobGrade.objects.all()
