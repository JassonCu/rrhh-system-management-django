"""Conjuntos cerrados de la relación laboral.

Interfaz pública de `contracts`: otras apps (`employees` para el alcance de
equipo) pueden consultar estos valores. Los **valores** son ASCII estable y no se
traducen: entran en `CheckConstraint`, consultas y auditoría (§O.3.1).
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContractType(models.TextChoices):
    INDEFINITE = "INDEFINITE", _("Indefinite term")
    FIXED_TERM = "FIXED_TERM", _("Fixed term")
    TEMPORARY = "TEMPORARY", _("Temporary")
    INTERNSHIP = "INTERNSHIP", _("Internship")


class ContractStatus(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    TERMINATED = "TERMINATED", _("Terminated")
    EXPIRED = "EXPIRED", _("Expired")


class TerminationReason(models.TextChoices):
    RESIGNATION = "RESIGNATION", _("Resignation")
    DISMISSAL_WITH_CAUSE = "DISMISSAL_WITH_CAUSE", _("Dismissal with just cause")
    DISMISSAL_WITHOUT_CAUSE = "DISMISSAL_WITHOUT_CAUSE", _("Dismissal without just cause")
    MUTUAL_AGREEMENT = "MUTUAL_AGREEMENT", _("Mutual agreement")
    CONTRACT_EXPIRY = "CONTRACT_EXPIRY", _("End of fixed term")
    RETIREMENT = "RETIREMENT", _("Retirement")
    DEATH = "DEATH", _("Death")


class PayFrequency(models.TextChoices):
    MONTHLY = "MONTHLY", _("Monthly")
    # Quincenal: dos pagos al mes (24 al año), que es la práctica habitual en
    # Guatemala. No es "cada dos semanas" (26 al año).
    BIWEEKLY = "BIWEEKLY", _("Twice a month")
    WEEKLY = "WEEKLY", _("Weekly")


class SalaryChangeReason(models.TextChoices):
    INITIAL = "INITIAL", _("Initial salary")
    MERIT_INCREASE = "MERIT_INCREASE", _("Merit increase")
    PROMOTION = "PROMOTION", _("Promotion")
    ADJUSTMENT = "ADJUSTMENT", _("Adjustment or correction")
    LEGAL_MINIMUM = "LEGAL_MINIMUM", _("Legal minimum wage update")
    DEMOTION = "DEMOTION", _("Demotion")


class AssignmentReason(models.TextChoices):
    INITIAL = "INITIAL", _("Initial assignment")
    PROMOTION = "PROMOTION", _("Promotion")
    TRANSFER = "TRANSFER", _("Transfer")
    REORGANIZATION = "REORGANIZATION", _("Reorganization")
    TEMPORARY_COVER = "TEMPORARY_COVER", _("Temporary cover")


#: Contratos que representan una relación laboral **viva**. Solo puede haber uno
#: por empleado (RN-13). Incluye SUSPENDED a propósito: un contrato suspendido
#: sigue vigente, y permitir otro activo a la vez sería un doble vínculo.
LIVE_STATUSES: frozenset[str] = frozenset(
    {ContractStatus.ACTIVE.value, ContractStatus.SUSPENDED.value}
)

#: Estados finales: el contrato ya no admite cambios.
FINAL_STATUSES: frozenset[str] = frozenset(
    {ContractStatus.TERMINATED.value, ContractStatus.EXPIRED.value}
)

#: Máquina de estados (§G.14). Cualquier transición no listada se rechaza en
#: lugar de asumirse.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ContractStatus.DRAFT.value: frozenset({ContractStatus.ACTIVE.value}),
    ContractStatus.ACTIVE.value: frozenset(
        {
            ContractStatus.SUSPENDED.value,
            ContractStatus.TERMINATED.value,
            ContractStatus.EXPIRED.value,
        }
    ),
    ContractStatus.SUSPENDED.value: frozenset(
        {
            ContractStatus.ACTIVE.value,
            ContractStatus.TERMINATED.value,
            ContractStatus.EXPIRED.value,
        }
    ),
    ContractStatus.TERMINATED.value: frozenset(),
    ContractStatus.EXPIRED.value: frozenset(),
}

#: Jornada completa. La suma de FTE de las asignaciones vigentes no la supera (RN-25).
MAX_FTE = Decimal("1.00")

#: Pagos al mes por frecuencia, para comparar con el salario mínimo mensual.
MONTHLY_FACTOR: dict[str, Decimal] = {
    PayFrequency.MONTHLY.value: Decimal("1"),
    PayFrequency.BIWEEKLY.value: Decimal("2"),
    PayFrequency.WEEKLY.value: Decimal("52") / Decimal("12"),
}
