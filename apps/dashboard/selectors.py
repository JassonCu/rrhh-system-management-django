"""Lecturas del inicio por rol.

Esta app **no tiene modelos**: compone la interfaz pública de `employees` y
`contracts` (ADR-009). Vive aparte de `core` porque `core` no puede depender de
ningún dominio, y un inicio útil necesita datos de varios.

Todo pasa por los selectores con alcance de cada app: el panel de un jefe
contiene lo que ese jefe ya podía ver, ni una fila más.
"""

from __future__ import annotations

from typing import Any

from apps.contracts import selectors as contracts
from apps.employees import selectors as employees
from apps.employees.constants import EmploymentStatus

#: Cuántas filas se listan en cada panel del inicio.
PREVIEW_SIZE = 5

#: Días de antelación con los que se avisa de un contrato por vencer.
EXPIRY_HORIZON_DAYS = 30


def own_employee(user):
    """Ficha de la persona que ha iniciado sesión, si tiene una."""
    if not user.is_authenticated:
        return None
    return employees.employees_visible_for(user).filter(user=user).first()


def own_live_contract(user):
    """Contrato vigente propio, si existe."""
    record = own_employee(user)
    if record is None:
        return None
    return contracts.live_contract_for(user, record)


def team_for(user, *, limit: int = PREVIEW_SIZE):
    """Equipo de un jefe: su alcance menos su propia ficha."""
    return employees.employees_visible_for(user).exclude(user=user)[:limit]


def hr_overview(user) -> dict[str, Any]:
    """Indicadores y pendientes de RRHH.

    **Sin importes**: el inicio es una pantalla que se deja abierta, así que no
    muestra salarios aunque quien mire tenga permiso (plan UX/UI §7.1).
    """
    visible_employees = employees.employees_visible_for(user)
    active = visible_employees.filter(employment_status=EmploymentStatus.ACTIVE)
    drafts = contracts.drafts_for(user)
    expiring = contracts.expiring_soon(user, days=EXPIRY_HORIZON_DAYS)
    without_contract = active.exclude(pk__in=contracts.employee_ids_with_live_contract())

    return {
        "active_employees": active.count(),
        "draft_contracts": drafts.count(),
        "expiring_contracts": expiring.count(),
        "employees_without_contract": without_contract.count(),
        "drafts": drafts.select_related("employee__person")[:PREVIEW_SIZE],
        "expiring": expiring.select_related("employee__person")[:PREVIEW_SIZE],
        "pending_employees": without_contract.select_related("person")[:PREVIEW_SIZE],
        "horizon_days": EXPIRY_HORIZON_DAYS,
    }
