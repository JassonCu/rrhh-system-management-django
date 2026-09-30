"""Constructores de reportes: de filtros a filas.

**Regla de la app:** aquí no se consulta el ORM de otras apps directamente. Cada
reporte se arma con los **selectores** de su app de origen, que ya aplican el
alcance de quien consulta (ADR-005). Un reporte que use `Model.objects` se
saltaría esa regla y enseñaría lo que la pantalla esconde.

Por eso un reporte de asistencia pedido por una jefatura trae a su equipo, y el
mismo reporte pedido por RRHH trae a toda la organización, sin una sola línea
de código que lo distinga.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from apps.attendance import selectors as attendance_selectors
from apps.attendance.constants import IncidentStatus, IncidentType
from apps.contracts import selectors as contract_selectors
from apps.documents import selectors as document_selectors
from apps.employees.selectors import employees_visible_for
from apps.leave import selectors as leave_selectors
from apps.reports.constants import EXPORT_ROW_LIMIT


@dataclass(frozen=True)
class Column:
    """Una columna del reporte. `key` es la clave de la fila; `label` se traduce."""

    key: str
    label: str
    numeric: bool = False


@dataclass
class ReportResult:
    """El reporte ya calculado: columnas, filas y totales.

    **Los totales cubren el período completo**, aunque las filas se recorten:
    recalcularlos sobre lo recortado daría un total que no es el del período y
    nadie lo notaría. Cada salida avisa cuando recortó.
    """

    columns: list[Column]
    rows: list[dict[str, Any]]
    totals: dict[str, Any]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class Filters:
    """Filtros ya validados por el formulario."""

    date_from: dt.date
    date_to: dt.date
    department: Any = None

    def describe(self) -> str:
        text = f"{self.date_from} — {self.date_to}"
        return f"{text} · {self.department}" if self.department else text


def _people(user, filters: Filters):
    """Personas al alcance, acotadas por departamento si se pidió.

    El departamento filtra **dentro** del alcance: nunca lo amplía.
    """
    people = employees_visible_for(user).select_related("person")
    if filters.department is not None:
        visible = [
            employee for employee in people if _department_of(employee) == filters.department.pk
        ]
        return visible
    return list(people)


def _department_of(employee) -> int | None:
    contract = contract_selectors.live_contract_of(employee.pk)
    if contract is None:
        return None
    assignment = contract_selectors.current_primary_assignment(contract)
    return assignment.position.department_id if assignment else None


def _minutes_to_hours(minutes: int) -> Decimal:
    return (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"))


def _count(incidents, incident_type: str) -> int:
    """Cuenta incidencias **sin resolver**.

    Una falta que alguien justificó —por ejemplo, la que abre una incapacidad
    aprobada después del cierre— dejaría el mismo reporte distinto según el
    orden en que ocurrieron las cosas.
    """
    return sum(
        1
        for incident in incidents
        if incident.incident_type == incident_type and incident.status != IncidentStatus.JUSTIFIED
    )


# --------------------------------------------------------------------------- #
# Asistencia
# --------------------------------------------------------------------------- #


def attendance_report(user, filters: Filters) -> ReportResult:
    columns = [
        Column("employee_code", _("Code")),
        Column("employee", _("Employee")),
        Column("expected_hours", _("Expected hours"), numeric=True),
        Column("worked_hours", _("Worked hours"), numeric=True),
        Column("balance_hours", _("Difference"), numeric=True),
        Column("late", _("Late arrivals"), numeric=True),
        Column("absences", _("Absences"), numeric=True),
    ]
    rows: list[dict[str, Any]] = []
    # Los totales se acumulan en **minutos** y se convierten una sola vez al
    # final: sumar horas ya redondeadas hace que el pie de la tabla no cuadre
    # con sus propias filas.
    expected_total = worked_total = 0
    for employee in _people(user, filters):
        days = attendance_selectors.period_summary(employee, filters.date_from, filters.date_to)
        expected = sum(day["expected_minutes"] for day in days)
        worked = sum(day["worked_minutes"] for day in days)
        expected_total += expected
        worked_total += worked
        incidents = [incident for day in days for incident in day["incidents"]]
        rows.append(
            {
                "employee_code": employee.employee_code,
                "employee": employee.person.full_name,
                "expected_hours": _minutes_to_hours(expected),
                "worked_hours": _minutes_to_hours(worked),
                "balance_hours": _minutes_to_hours(worked - expected),
                "late": _count(incidents, IncidentType.LATE),
                "absences": _count(incidents, IncidentType.ABSENCE),
            }
        )

    totals = {
        "expected_hours": _minutes_to_hours(expected_total),
        "worked_hours": _minutes_to_hours(worked_total),
        "balance_hours": _minutes_to_hours(worked_total - expected_total),
        "late": sum(row["late"] for row in rows),
        "absences": sum(row["absences"] for row in rows),
    }
    return _limited(ReportResult(columns=columns, rows=rows, totals=totals))


# --------------------------------------------------------------------------- #
# Ausencias
# --------------------------------------------------------------------------- #


def leave_report(user, filters: Filters) -> ReportResult:
    columns = [
        Column("employee_code", _("Code")),
        Column("employee", _("Employee")),
        Column("leave_type", _("Type")),
        Column("start_date", _("From")),
        Column("end_date", _("To")),
        Column("working_days", _("Working days"), numeric=True),
        Column("status", _("Status")),
        Column("balance", _("Balance today"), numeric=True),
    ]
    people = {employee.pk: employee for employee in _people(user, filters)}
    requests = (
        leave_selectors.requests_visible_for(user)
        .filter(
            employee__in=people.keys(),
            start_date__lte=filters.date_to,
            end_date__gte=filters.date_from,
        )
        .order_by("employee__person__last_name", "start_date")
    )

    balances: dict[tuple[int, int], Decimal] = {}
    rows: list[dict[str, Any]] = []
    for item in requests:
        key = (item.employee_id, item.leave_type_id)
        if key not in balances:
            balances[key] = leave_selectors.balance_for(item.employee, item.leave_type)
        rows.append(
            {
                "employee_code": item.employee.employee_code,
                "employee": item.employee.person.full_name,
                "leave_type": item.leave_type.name,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "working_days": item.working_days,
                "status": item.get_status_display(),
                "balance": balances[key],
            }
        )

    totals = {"working_days": sum((row["working_days"] for row in rows), Decimal("0"))}
    return _limited(ReportResult(columns=columns, rows=rows, totals=totals))


# --------------------------------------------------------------------------- #
# Plantilla y contratos
# --------------------------------------------------------------------------- #


def headcount_report(user, filters: Filters) -> ReportResult:
    """Plantilla con su contrato. **Sin importes**: el salario tiene su propio
    permiso y un reporte no es la puerta de atrás para verlo (§J.2)."""
    columns = [
        Column("employee_code", _("Code")),
        Column("employee", _("Employee")),
        Column("hire_date", _("Hire date")),
        Column("status", _("Status")),
        Column("contract_type", _("Contract")),
        Column("contract_start", _("Contract start")),
        Column("contract_end", _("Contract end")),
        Column("position", _("Position")),
    ]
    rows: list[dict[str, Any]] = []
    for employee in _people(user, filters):
        contract = contract_selectors.live_contract_of(employee.pk)
        assignment = contract_selectors.current_primary_assignment(contract) if contract else None
        rows.append(
            {
                "employee_code": employee.employee_code,
                "employee": employee.person.full_name,
                "hire_date": employee.hire_date,
                "status": employee.get_employment_status_display(),
                "contract_type": contract.get_contract_type_display() if contract else "—",
                "contract_start": contract.start_date if contract else None,
                "contract_end": contract.end_date if contract else None,
                "position": assignment.position.title if assignment else "—",
            }
        )

    ending = [
        row
        for row in rows
        if row["contract_end"] and filters.date_from <= row["contract_end"] <= filters.date_to
    ]
    totals = {
        "employee_code": _("%(count)s people") % {"count": len(rows)},
        "contract_end": _("%(count)s ending") % {"count": len(ending)},
    }
    return _limited(ReportResult(columns=columns, rows=rows, totals=totals))


# --------------------------------------------------------------------------- #
# Expedientes
# --------------------------------------------------------------------------- #


def documents_report(user, filters: Filters) -> ReportResult:
    """Qué hay en cada expediente y qué vence. **No** revela el contenido de un
    documento confidencial: solo que existe, igual que la ficha (ADR-023)."""
    columns = [
        Column("employee_code", _("Code")),
        Column("employee", _("Employee")),
        Column("document_type", _("Type")),
        Column("title", _("Title")),
        Column("issued_on", _("Issued")),
        Column("expires_on", _("Expires")),
        Column("state", _("Status")),
    ]
    people = {employee.pk for employee in _people(user, filters)}
    documents = (
        document_selectors.documents_visible_for(user)
        .filter(employee__in=people)
        .order_by("employee__person__last_name", "expires_on")
    )

    rows: list[dict[str, Any]] = []
    expiring = 0
    for document in documents:
        in_window = (
            document.expires_on is not None
            and filters.date_from <= document.expires_on <= filters.date_to
        )
        expiring += 1 if in_window else 0
        rows.append(
            {
                "employee_code": document.employee.employee_code,
                "employee": document.employee.person.full_name,
                "document_type": document.document_type.name,
                "title": (
                    document.title
                    if document_selectors.can_open(user, document)
                    else _("Confidential document")
                ),
                "issued_on": document.issued_on,
                "expires_on": document.expires_on,
                "state": _("expired")
                if document.is_expired
                else (_("expiring soon") if in_window else _("current")),
            }
        )

    totals = {
        "employee_code": _("%(count)s documents") % {"count": len(rows)},
        "expires_on": _("%(count)s in the period") % {"count": expiring},
    }
    return _limited(ReportResult(columns=columns, rows=rows, totals=totals))


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #

BUILDERS = {
    "attendance": attendance_report,
    "leave": leave_report,
    "headcount": headcount_report,
    "documents": documents_report,
}


def _limited(result: ReportResult) -> ReportResult:
    """Corta el reporte en el tope y **lo dice**: un total a medias engaña."""
    if len(result.rows) > EXPORT_ROW_LIMIT:
        result.rows = result.rows[:EXPORT_ROW_LIMIT]
        result.truncated = True
    return result
