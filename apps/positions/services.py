"""Casos de uso del catálogo de puestos."""

from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.contracts.selectors import position_is_occupied
from apps.core.exceptions import ConflictError
from apps.positions.models import JobGrade, Position


@transaction.atomic
def create_position(*, actor, request: HttpRequest, **fields) -> Position:
    position = Position(**fields)
    position.full_clean()
    position.save()

    record(
        action=AuditAction.POSITION_CREATE,
        actor=actor,
        obj=position,
        request=request,
        metadata={
            "code": position.code,
            "department": str(position.department),
            "job_grade": str(position.job_grade),
        },
    )
    return position


@transaction.atomic
def update_position(*, position: Position, actor, request: HttpRequest, **fields) -> Position:
    previous = {
        "title": position.title,
        "department": str(position.department),
        "job_grade": str(position.job_grade),
    }
    for key, value in fields.items():
        setattr(position, key, value)
    position.full_clean()
    position.save()

    record(
        action=AuditAction.POSITION_UPDATE,
        actor=actor,
        obj=position,
        request=request,
        metadata={"from": previous},
    )
    return position


@transaction.atomic
def deactivate_position(*, position: Position, actor, request: HttpRequest) -> Position:
    """Baja lógica del puesto.

    No se desactiva un puesto ocupado, ni uno comprometido en un contrato
    pendiente: dejaría a alguien sin puesto válido.
    """
    if position_is_occupied(position.pk):
        raise ConflictError("position_is_occupied", position=position.code)

    position.is_active = False
    position.save(update_fields=["is_active", "updated_at"])

    record(action=AuditAction.POSITION_DEACTIVATE, actor=actor, obj=position, request=request)
    return position


@transaction.atomic
def create_job_grade(*, actor, request: HttpRequest, **fields) -> JobGrade:
    grade = JobGrade(**fields)
    grade.full_clean()
    grade.save()

    record(
        action=AuditAction.JOB_GRADE_CREATE,
        actor=actor,
        obj=grade,
        request=request,
        # Los importes NO entran en la metadata: la banda salarial es
        # confidencial (§G.19) y la bitácora la consulta el rol AUDITOR.
        metadata={"code": grade.code, "level": grade.level},
    )
    return grade


@transaction.atomic
def update_job_grade(*, grade: JobGrade, actor, request: HttpRequest, **fields) -> JobGrade:
    for key, value in fields.items():
        setattr(grade, key, value)
    grade.full_clean()
    grade.save()

    if grade.min_salary > grade.max_salary:  # pragma: no cover - full_clean ya lo impide
        raise ConflictError("job_grade_range_inverted")

    record(
        action=AuditAction.JOB_GRADE_UPDATE,
        actor=actor,
        obj=grade,
        request=request,
        metadata={"code": grade.code},
    )
    return grade
