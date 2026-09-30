"""Catálogos de ausencias.

Los **valores** son ASCII estable y nunca se traducen (§O.3.1).
"""

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


class LeaveStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Pending approval")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")
    CANCELLED = "CANCELLED", _("Cancelled")


class EntitlementSource(models.TextChoices):
    ACCRUAL = "ACCRUAL", _("Monthly accrual")
    MANUAL = "MANUAL", _("Granted by HR")
    CARRYOVER = "CARRYOVER", _("Carried over")


class LedgerEntryType(models.TextChoices):
    ACCRUAL = "ACCRUAL", _("Accrual")
    CONSUMPTION = "CONSUMPTION", _("Consumption")
    REVERSAL = "REVERSAL", _("Reversal")
    ADJUSTMENT = "ADJUSTMENT", _("Adjustment")


#: Transiciones válidas (RN-45). Lo que no está aquí, no ocurre.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    LeaveStatus.DRAFT: frozenset({LeaveStatus.SUBMITTED, LeaveStatus.CANCELLED}),
    LeaveStatus.SUBMITTED: frozenset(
        {LeaveStatus.APPROVED, LeaveStatus.REJECTED, LeaveStatus.CANCELLED}
    ),
    # Una solicitud aprobada solo se cancela **antes** de empezar y por RRHH.
    LeaveStatus.APPROVED: frozenset({LeaveStatus.CANCELLED}),
    LeaveStatus.REJECTED: frozenset(),
    LeaveStatus.CANCELLED: frozenset(),
}

#: Estados que ocupan calendario y saldo: cuentan para el traslape (RN-41).
BLOCKING_STATUSES = (LeaveStatus.SUBMITTED, LeaveStatus.APPROVED)

#: Estados finales.
FINAL_STATUSES = (LeaveStatus.APPROVED, LeaveStatus.REJECTED, LeaveStatus.CANCELLED)

#: Meses del año, para el devengo proporcional.
MONTHS_PER_YEAR = 12

#: Máximo de días que puede tener un derecho anual. Más que eso es un error de
#: captura, no una política.
MAX_ANNUAL_DAYS = 60

#: Máximo de días hacia atrás con que un tipo puede admitir registros. Más que
#: eso deja de ser «se reportó tarde» y pasa a ser reescribir la asistencia.
MAX_BACKDATING_DAYS = 30

#: Precisión con la que se guardan los días: dos decimales. El devengo
#: mensual reparte por diferencia para que doce meses sumen el año exacto.
DAYS_QUANTUM = Decimal("0.01")
