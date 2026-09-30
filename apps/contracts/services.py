"""Casos de uso de la relación laboral.

Aquí viven las invariantes que la base no puede expresar de forma portable
(§E.4): no traslape de contratos, continuidad salarial, suma de FTE, contención
de fechas y la coherencia del estado laboral del empleado.

**Este es el único lugar que modifica `Employee.employment_status`** (RN-18,
ADR-012), siempre en la misma transacción que el contrato que lo provoca.

Concurrencia: cada operación bloquea la fila del contrato y, cuando afecta al
estado laboral, la del empleado. En PostgreSQL eso serializa las operaciones
concurrentes sobre la misma persona; SQLite ignora `select_for_update`, y ahí la
última defensa son los índices únicos parciales.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.contracts import selectors
from apps.contracts.constants import (
    ALLOWED_TRANSITIONS,
    FINAL_STATUSES,
    LIVE_STATUSES,
    MAX_FTE,
    MONTHLY_FACTOR,
    AssignmentReason,
    ContractStatus,
    PayFrequency,
    TerminationReason,
)
from apps.contracts.models import Assignment, ContractSalary, EmploymentContract
from apps.core.exceptions import ConflictError
from apps.employees.constants import EmploymentStatus

ONE_DAY = dt.timedelta(days=1)


def _employee_model():
    return EmploymentContract._meta.get_field("employee").related_model


# --------------------------------------------------------------------------- #
# Contrato
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_contract(
    *, employee, actor, request: HttpRequest | None, **fields
) -> EmploymentContract:
    """Crea un contrato en BORRADOR.

    Un borrador no produce efectos: no cambia el estado del empleado ni cuenta
    para el traslape. Se activa cuando tiene salario y puesto.
    """
    _ensure_not_own_employment(employee.user_id, actor)
    contract = EmploymentContract(employee=employee, status=ContractStatus.DRAFT, **fields)
    contract.full_clean()
    contract.save()

    record(
        action=AuditAction.CONTRACT_CREATE,
        actor=actor,
        obj=contract,
        request=request,
        metadata={"employee_code": employee.employee_code, "contract_type": contract.contract_type},
    )
    return contract


@transaction.atomic
def activate_contract(
    *, contract: EmploymentContract, actor, request: HttpRequest | None
) -> EmploymentContract:
    """BORRADOR → ACTIVO. Aquí se exigen todas las invariantes del vínculo."""
    contract = _lock_contract(contract, actor)
    employee = _lock_employee(contract.employee_id)

    if contract.status != ContractStatus.DRAFT:
        raise ConflictError(
            "invalid_contract_transition", current=contract.status, target=ContractStatus.ACTIVE
        )
    # RN-20 y RN-21: el primer salario arranca con el contrato.
    if not contract.salaries.filter(effective_from=contract.start_date).exists():
        raise ConflictError("contract_needs_salary")
    # RN-24: hay un puesto principal abierto.
    if not contract.assignments.filter(is_primary=True, end_date__isnull=True).exists():
        raise ConflictError("contract_needs_primary_assignment")
    # RN-13 con mensaje legible; el índice único parcial lo garantiza igualmente.
    if (
        EmploymentContract.objects.filter(
            employee_id=contract.employee_id, status__in=LIVE_STATUSES
        )
        .exclude(pk=contract.pk)
        .exists()
    ):
        raise ConflictError("employee_has_live_contract")
    _ensure_no_overlap(contract)
    # RN-23: el salario pudo registrarse antes que el puesto; se revalida aquí.
    salary = contract.salaries.filter(effective_to__isnull=True).first()
    if (
        salary
        and not salary.justification
        and _is_out_of_band(contract, salary.amount, salary.currency, salary.effective_from)
    ):
        raise ConflictError("salary_out_of_band_requires_justification")

    contract.status = ContractStatus.ACTIVE
    try:
        with transaction.atomic():
            contract.save(update_fields=["status", "updated_at"])
    except IntegrityError as error:  # pragma: no cover - carrera entre dos activaciones
        raise ConflictError("employee_has_live_contract") from error

    _sync_employee_status(employee)
    _record_transition(contract, ContractStatus.DRAFT, actor, request)
    return contract


@transaction.atomic
def suspend_contract(
    *, contract: EmploymentContract, actor, request: HttpRequest | None
) -> EmploymentContract:
    return _simple_transition(contract, ContractStatus.SUSPENDED, actor, request)


@transaction.atomic
def resume_contract(
    *, contract: EmploymentContract, actor, request: HttpRequest | None
) -> EmploymentContract:
    return _simple_transition(contract, ContractStatus.ACTIVE, actor, request)


@transaction.atomic
def terminate_contract(
    *,
    contract: EmploymentContract,
    termination_date: dt.date,
    reason: str,
    actor,
    request: HttpRequest | None,
) -> EmploymentContract:
    """Baja del contrato y, si no queda otro vínculo vivo, del empleado.

    Cierra en el mismo acto el salario y las asignaciones abiertas, y desactiva la
    cuenta del empleado: una cuenta activa de alguien dado de baja es un hallazgo
    de auditoría clásico.
    """
    contract = _lock_contract(contract, actor)
    employee = _lock_employee(contract.employee_id)

    _ensure_transition(contract, ContractStatus.TERMINATED)
    # Una baja con fecha futura cortaría hoy el acceso y sacaría hoy a la persona
    # del equipo de su jefe: el estado se adelantaría a los hechos. Las bajas
    # se registran el día en que ocurren, o después.
    if termination_date > selectors._day(None):
        raise ConflictError("termination_in_future")
    if reason not in TerminationReason.values:
        raise ConflictError("invalid_termination_reason", reason=reason)
    if termination_date < contract.start_date:
        raise ConflictError("termination_before_start")
    if contract.end_date and termination_date > contract.end_date:
        raise ConflictError("termination_after_contract_end")

    _close_open_periods(contract, termination_date)

    previous = contract.status
    contract.status = ContractStatus.TERMINATED
    contract.termination_date = termination_date
    contract.termination_reason = reason
    contract.save(update_fields=["status", "termination_date", "termination_reason", "updated_at"])

    _sync_employee_status(employee)
    _deactivate_account_if_terminated(employee, actor, request, reason)

    record(
        action=AuditAction.CONTRACT_TERMINATE,
        actor=actor,
        obj=contract,
        request=request,
        metadata={
            "from": previous,
            "reason": reason,
            "termination_date": termination_date.isoformat(),
        },
    )
    return contract


def expire_contracts(*, today: dt.date | None = None) -> int:
    """Marca como EXPIRED los contratos vivos cuya fecha de fin ya pasó.

    Lo ejecuta el sistema (`manage.py expire_contracts`), así que no hay actor
    humano. Cada contrato se procesa en su propia transacción: un fallo en uno no
    debe impedir que venzan los demás.
    """
    day = today or selectors._day(None)
    expired = 0
    due = EmploymentContract.objects.filter(status__in=LIVE_STATUSES, end_date__lt=day)

    for candidate in due.values_list("pk", flat=True):
        with transaction.atomic():
            contract = EmploymentContract.objects.select_for_update().get(pk=candidate)
            if contract.status not in LIVE_STATUSES:
                continue
            employee = _lock_employee(contract.employee_id)

            _close_open_periods(contract, contract.end_date)
            previous = contract.status
            contract.status = ContractStatus.EXPIRED
            contract.save(update_fields=["status", "updated_at"])

            _sync_employee_status(employee)
            _deactivate_account_if_terminated(employee, None, None, "contract expired")
            _record_transition(contract, previous, None, None)
            expired += 1
    return expired


def record_salary_access(*, contract: EmploymentContract, actor, request: HttpRequest) -> None:
    """Deja constancia de que un tercero consultó el historial salarial.

    Mismo criterio que los datos personales sensibles (§K.5): controlar quién
    **puede** ver importes no basta, hay que poder responder quién los vio.
    """
    record(
        action=AuditAction.SALARY_VIEW,
        actor=actor,
        obj=contract,
        request=request,
        metadata={"employee_code": contract.employee.employee_code},
    )


# --------------------------------------------------------------------------- #
# Salario
# --------------------------------------------------------------------------- #


@transaction.atomic
def set_salary(
    *,
    contract: EmploymentContract,
    amount: Decimal,
    effective_from: dt.date,
    change_reason: str,
    actor,
    request: HttpRequest | None,
    currency: str = "GTQ",
    pay_frequency: str = PayFrequency.MONTHLY,
    justification: str = "",
) -> ContractSalary:
    """Registra un salario nuevo, cerrando el anterior sin dejar huecos (RN-21).

    Nunca se sobrescribe un importe: el anterior se cierra el día previo al
    nuevo, de modo que la historia queda contigua y reproducible para nómina.
    """
    contract = _lock_contract(contract, actor)
    _ensure_not_final(contract)
    _ensure_within_contract(contract, effective_from, "salary_outside_contract")
    _validate_minimum_wage(amount, pay_frequency)

    justification = (justification or "").strip()
    previous = contract.salaries.filter(effective_to__isnull=True).first()
    if previous is None:
        if effective_from != contract.start_date:
            raise ConflictError("first_salary_must_start_with_contract")
    else:
        if effective_from <= previous.effective_from:
            raise ConflictError("salary_not_after_previous")
        previous.effective_to = effective_from - ONE_DAY
        previous.save(update_fields=["effective_to", "updated_at"])

    out_of_band = _is_out_of_band(contract, amount, currency, effective_from)
    if out_of_band and not justification:
        raise ConflictError("salary_out_of_band_requires_justification")

    salary = ContractSalary(
        contract=contract,
        amount=amount,
        currency=currency,
        pay_frequency=pay_frequency,
        effective_from=effective_from,
        change_reason=change_reason,
        justification=justification,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    salary.full_clean()
    salary.save()

    record(
        action=AuditAction.SALARY_CHANGE,
        actor=actor,
        obj=contract,
        request=request,
        # SIN importes: el historial con cifras vive en ContractSalary, protegido
        # por `view_salary`. La bitácora registra quién, cuándo y por qué.
        metadata={
            "change_reason": change_reason,
            "effective_from": effective_from.isoformat(),
            "out_of_band": out_of_band,
        },
    )
    return salary


# --------------------------------------------------------------------------- #
# Asignaciones
# --------------------------------------------------------------------------- #


@transaction.atomic
def add_assignment(
    *,
    contract: EmploymentContract,
    position,
    start_date: dt.date,
    actor,
    request: HttpRequest | None,
    fte: Decimal = MAX_FTE,
    is_primary: bool = True,
    assignment_reason: str = AssignmentReason.INITIAL,
) -> Assignment:
    """Asigna un puesto dentro del contrato.

    Una asignación principal nueva **sustituye** a la anterior, que se cierra el
    día previo: un traslado o una promoción no dejan historia sobrescrita.
    """
    contract = _lock_contract(contract, actor)
    _ensure_not_final(contract)
    _ensure_within_contract(contract, start_date, "assignment_outside_contract")
    if not position.is_active:
        raise ConflictError("position_inactive", position=position.code)
    # El puesto cuelga de un departamento, y este de una empresa: un puesto de
    # otra empresa mezclaría dos patronos en un mismo contrato.
    if position.department.company_id != contract.company_id:
        raise ConflictError("position_in_another_company", position=position.code)

    fte = Decimal(fte)
    if is_primary:
        previous_primary = contract.assignments.filter(
            is_primary=True, end_date__isnull=True
        ).first()
        if previous_primary is not None:
            if start_date <= previous_primary.start_date:
                raise ConflictError("assignment_not_after_previous_primary")
            previous_primary.end_date = start_date - ONE_DAY
            previous_primary.save(update_fields=["end_date", "updated_at"])

    # RN-25: se cuentan todas las asignaciones que siguen abiertas en esa fecha,
    # incluidas las que empiezan después: la nueva es abierta y se solapa con ellas.
    overlapping = contract.assignments.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=start_date)
    )
    total = sum((assignment.fte for assignment in overlapping), Decimal("0")) + fte
    if total > MAX_FTE:
        raise ConflictError("fte_exceeds_full_time", total=str(total))

    assignment = Assignment(
        contract=contract,
        position=position,
        start_date=start_date,
        fte=fte,
        is_primary=is_primary,
        assignment_reason=assignment_reason,
    )
    assignment.full_clean()
    assignment.save()

    record(
        action=AuditAction.ASSIGNMENT_CREATE,
        actor=actor,
        obj=contract,
        request=request,
        metadata={
            "position": position.code,
            "department": position.department.code,
            "fte": str(fte),
            "is_primary": is_primary,
            "start_date": start_date.isoformat(),
        },
    )
    return assignment


@transaction.atomic
def end_assignment(
    *, assignment: Assignment, end_date: dt.date, actor, request: HttpRequest | None
) -> Assignment:
    contract = _lock_contract(assignment.contract, actor)
    assignment = Assignment.objects.select_for_update().get(pk=assignment.pk)

    if assignment.end_date is not None:
        raise ConflictError("assignment_already_ended")
    if end_date < assignment.start_date:
        raise ConflictError("assignment_end_before_start")
    # RN-24: un contrato vivo no puede quedarse sin puesto principal. Para
    # cambiarlo se añade el nuevo, que cierra el anterior.
    if assignment.is_primary and contract.status in LIVE_STATUSES:
        raise ConflictError("contract_needs_primary_assignment")

    assignment.end_date = end_date
    assignment.save(update_fields=["end_date", "updated_at"])

    record(
        action=AuditAction.ASSIGNMENT_END,
        actor=actor,
        obj=contract,
        request=request,
        metadata={"position": assignment.position.code, "end_date": end_date.isoformat()},
    )
    return assignment


# --------------------------------------------------------------------------- #
# Invariantes y utilidades internas
# --------------------------------------------------------------------------- #


def _lock_contract(contract: EmploymentContract, actor) -> EmploymentContract:
    """Bloquea el contrato y aplica la separación de funciones.

    Todos los casos de uso con actor humano pasan por aquí, así que la regla no
    depende de que cada servicio se acuerde de comprobarla.
    """
    locked = EmploymentContract.objects.select_for_update().get(pk=contract.pk)
    holder = (
        _employee_model()
        .objects.filter(pk=locked.employee_id)
        .values_list("user_id", flat=True)
        .first()
    )
    _ensure_not_own_employment(holder, actor)
    return locked


def _ensure_not_own_employment(holder_user_id: int | None, actor) -> None:
    """Separación de funciones: nadie modifica su propia relación laboral.

    Sin esta regla, quien tiene `change_salary` podría subirse el sueldo y quien
    tiene `add_assignment` podría promoverse. El permiso dice **qué** puede
    hacer alguien; esta regla dice **sobre quién** no puede hacerlo. Aplica
    también a SUPERADMIN: nadie aprueba sus propios cambios.
    """
    actor_id = getattr(actor, "pk", None)
    if actor_id is not None and holder_user_id == actor_id:
        raise ConflictError("cannot_change_own_employment")


def _lock_employee(employee_id: int):
    return _employee_model().objects.select_for_update().get(pk=employee_id)


def _ensure_not_final(contract: EmploymentContract) -> None:
    if contract.status in FINAL_STATUSES:
        raise ConflictError("contract_is_closed", status=contract.status)


def _ensure_transition(contract: EmploymentContract, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS[contract.status]:
        raise ConflictError("invalid_contract_transition", current=contract.status, target=target)


def _ensure_within_contract(contract: EmploymentContract, day: dt.date, code: str) -> None:
    """RN-26: salarios y asignaciones caen dentro del contrato."""
    if not contract.covers(day):
        raise ConflictError(code, day=day.isoformat())


def _ensure_no_overlap(contract: EmploymentContract) -> None:
    """RN-14: los contratos no borradores de un empleado no se solapan.

    Un fin abierto cuenta como infinito. PostgreSQL permitiría expresarlo con
    `ExclusionConstraint`; SQLite no, así que vive aquí (ADR-002, ADR-003).
    """
    start, end = contract.start_date, contract.effective_end
    others = (
        EmploymentContract.objects.filter(employee_id=contract.employee_id)
        .exclude(pk=contract.pk)
        .exclude(status=ContractStatus.DRAFT)
    )
    for other in others:
        other_end = other.effective_end
        starts_before_other_ends = other_end is None or start <= other_end
        other_starts_before_this_ends = end is None or other.start_date <= end
        if starts_before_other_ends and other_starts_before_this_ends:
            raise ConflictError("contract_overlap", other=str(other.public_id))


def _simple_transition(contract, target, actor, request) -> EmploymentContract:
    contract = _lock_contract(contract, actor)
    employee = _lock_employee(contract.employee_id)
    _ensure_transition(contract, target)

    previous = contract.status
    contract.status = target
    contract.save(update_fields=["status", "updated_at"])

    _sync_employee_status(employee)
    _record_transition(contract, previous, actor, request)
    return contract


def _record_transition(contract, previous: str, actor, request) -> None:
    record(
        action=AuditAction.CONTRACT_UPDATE,
        actor=actor,
        obj=contract,
        request=request,
        metadata={"from": previous, "to": contract.status},
    )


def _close_open_periods(contract: EmploymentContract, day: dt.date) -> None:
    """Cierra salario y asignaciones abiertos en la fecha de fin del vínculo.

    Si hay un salario o una asignación que **empieza después** de esa fecha (un
    aumento programado, un traslado futuro), no se inventa un cierre: se rechaza,
    porque cualquier fecha elegida falsearía la historia.
    """
    if contract.salaries.filter(effective_from__gt=day).exists():
        raise ConflictError("salary_starts_after_termination")
    if contract.assignments.filter(start_date__gt=day).exists():
        raise ConflictError("assignment_starts_after_termination")

    contract.salaries.filter(effective_to__isnull=True).update(effective_to=day)
    contract.assignments.filter(end_date__isnull=True).update(end_date=day)


def _is_out_of_band(contract, amount: Decimal, currency: str, on: dt.date) -> bool:
    """RN-23: el importe cae fuera de la banda del puesto principal vigente.

    Sin puesto principal todavía no hay banda contra la que comparar; la
    comprobación se repite al activar. Una moneda distinta de la de la banda se
    trata como fuera de banda: no hay forma honesta de compararlas (supuesto S-03).
    """
    primary = selectors.current_primary_assignment(contract, on)
    if primary is None:
        return False
    grade = primary.position.job_grade
    if grade.currency != currency:
        return True
    return not grade.contains(amount)


def _validate_minimum_wage(amount: Decimal, pay_frequency: str) -> None:
    """RN-22: el equivalente mensual no baja del mínimo configurado.

    El mínimo es un **ajuste de entorno** y no una constante: cambia por acuerdo
    gubernativo y por actividad económica. Sin configurar, no se comprueba.
    """
    minimum = getattr(settings, "CONTRACTS_MINIMUM_MONTHLY_SALARY", None)
    if minimum is None:
        return
    monthly_equivalent = Decimal(amount) * MONTHLY_FACTOR[pay_frequency]
    if monthly_equivalent < minimum:
        raise ConflictError("salary_below_legal_minimum")


def _sync_employee_status(employee) -> None:
    """Materializa el estado laboral a partir de los contratos (RN-18, ADR-012).

    Es la **única** función que escribe `employment_status`. ON_LEAVE se respeta
    sobre un contrato activo: lo gestionará el módulo de ausencias.
    """
    expected, termination_date = selectors.expected_employment_status(employee.pk)
    if expected is None:
        return
    if (
        expected == EmploymentStatus.ACTIVE.value
        and employee.employment_status == EmploymentStatus.ON_LEAVE.value
    ):
        return
    if employee.employment_status == expected and employee.termination_date == termination_date:
        return

    employee.employment_status = expected
    employee.termination_date = termination_date
    employee.save(update_fields=["employment_status", "termination_date", "updated_at"])


def _deactivate_account_if_terminated(employee, actor, request, reason: str) -> None:
    if employee.employment_status != EmploymentStatus.TERMINATED.value:
        return
    user = employee.user
    if user is None or not user.is_active:
        return

    from apps.accounts.services import deactivate_user

    deactivate_user(user=user, actor=actor, request=request, reason=f"employment ended: {reason}")
