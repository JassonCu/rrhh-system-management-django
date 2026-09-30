"""Casos de uso sobre personas y empleados.

Transaccionales y auditados. Aquí viven las invariantes que necesitan más de una
fila —la edad mínima exige cruzar `Person` con `Employee`— y que por tanto no
caben en un `CheckConstraint` (§E.4).
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.http import HttpRequest

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.core.exceptions import ConflictError
from apps.employees.constants import MINIMUM_WORKING_AGE, EmploymentStatus
from apps.employees.models import Employee, IdentityDocument, Person


@transaction.atomic
def create_employee(
    *,
    actor,
    request: HttpRequest,
    person_data: dict,
    employee_code: str,
    hire_date: dt.date,
    user=None,
) -> Employee:
    """Da de alta a una persona y su identidad laboral, de forma atómica.

    Si algo falla, **no queda una `Person` huérfana**: el alta es un solo hecho
    del dominio aunque toque dos tablas.
    """
    person = Person(**person_data)
    person.full_clean()
    person.save()

    _validate_minimum_age(person, hire_date)

    employee = Employee(
        person=person,
        user=user,
        employee_code=employee_code.strip().upper(),
        hire_date=hire_date,
        employment_status=EmploymentStatus.ACTIVE,
    )
    employee.full_clean()
    employee.save()

    record(
        action=AuditAction.EMPLOYEE_CREATE,
        actor=actor,
        obj=employee,
        request=request,
        # El nombre sí; la fecha de nacimiento NO: es PII sensible y la bitácora
        # la lee el rol AUDITOR (§G.19, RN-72).
        metadata={"employee_code": employee.employee_code, "name": person.full_name},
    )
    return employee


@transaction.atomic
def update_person(*, person: Person, actor, request: HttpRequest, **fields) -> Person:
    changed = sorted(fields)
    for key, value in fields.items():
        setattr(person, key, value)
    person.full_clean()
    person.save()

    record(
        action=AuditAction.EMPLOYEE_UPDATE,
        actor=actor,
        obj=person,
        request=request,
        # Se registran **qué campos** cambiaron, no sus valores: un diff de PII
        # convertiría la bitácora en una copia del expediente.
        metadata={"changed_fields": changed},
    )
    return person


@transaction.atomic
def add_identity_document(
    *, person: Person, actor, request: HttpRequest, **fields
) -> IdentityDocument:
    document = IdentityDocument(person=person, **fields)
    document.full_clean()
    document.save()

    record(
        action=AuditAction.EMPLOYEE_UPDATE,
        actor=actor,
        obj=document,
        request=request,
        # Solo el tipo. **Nunca el número**: es PII sensible (RN-72). El filtro
        # de `sanitize_metadata` lo depuraría igualmente, pero no se pasa.
        metadata={"document_type": document.document_type},
    )
    return document


def record_sensitive_access(*, employee: Employee, actor, request: HttpRequest) -> None:
    """Deja constancia de que alguien consultó datos personales sensibles.

    No basta con controlar quién **puede** verlos: en un expediente laboral hay
    que poder responder quién los vio y cuándo (§K.5).
    """
    record(
        action=AuditAction.EMPLOYEE_VIEW_SENSITIVE,
        actor=actor,
        obj=employee,
        request=request,
        metadata={"employee_code": employee.employee_code},
    )


def _validate_minimum_age(person: Person, hire_date: dt.date) -> None:
    """RN-04: edad mínima a la fecha de ingreso.

    Cruza dos entidades, así que no cabe en un `CheckConstraint`. El mínimo es un
    parámetro y no una constante en el código porque la ley admite excepciones
    para menores con autorización.
    """
    age = person.age_at(hire_date)
    if age < MINIMUM_WORKING_AGE:
        raise ConflictError("employee_below_minimum_age", age=age, minimum=MINIMUM_WORKING_AGE)
