"""Relación laboral: contratos, historial salarial y asignaciones.

Es el agregado más importante del sistema (§A.2.2). El contrato es la raíz: el
salario y el puesto son **cláusulas del contrato**, no atributos del empleado, y
por eso cuelgan de aquí con vigencia propia.

Dos ausencias deliberadas en `Assignment`, por el mismo motivo (3NF, §D.5):

* sin `employee_id`: `contract → employee`, sería transitivo;
* sin `department_id`: `position → department` (ADR-011), también transitivo.

Ver docs/database/02-modelo-relacional.md §B.6 y el diccionario §G.14-G.16.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.contracts.constants import (
    AssignmentReason,
    ContractStatus,
    ContractType,
    PayFrequency,
    SalaryChangeReason,
    TerminationReason,
)
from apps.core.constants import CURRENCY_CODE_LENGTH
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_currency_code

_LIVE = [ContractStatus.ACTIVE.value, ContractStatus.SUSPENDED.value]
_TERMINATED = ContractStatus.TERMINATED.value


class EmploymentContract(TimeStampedModel):
    """Contrato de trabajo. Un hecho jurídico: una vez activo, nunca se borra."""

    public_id = models.UUIDField(
        _("public ID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("Used in URLs. It does not replace authorization."),
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name=_("employee"),
    )
    company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="contracts",
        verbose_name=_("employer"),
    )
    contract_type = models.CharField(_("contract type"), max_length=20, choices=ContractType)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(
        _("end date"),
        null=True,
        blank=True,
        help_text=_("Required for fixed-term contracts; empty for indefinite ones."),
    )
    probation_end_date = models.DateField(_("end of probation"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=20, choices=ContractStatus, default=ContractStatus.DRAFT
    )
    termination_reason = models.CharField(
        _("termination reason"),
        max_length=40,
        choices=TerminationReason,
        blank=True,
        default="",
    )
    termination_date = models.DateField(_("termination date"), null=True, blank=True)
    signed_on = models.DateField(_("signed on"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("employment contract")
        verbose_name_plural = _("employment contracts")
        ordering = ("-start_date",)
        permissions = [("terminate_contract", _("Can terminate employment contracts"))]
        constraints = [
            # RN-13, la regla de negocio más importante del sistema, garantizada
            # por la base y no por Python: un solo vínculo vivo por empleado.
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(status__in=_LIVE),
                name="uniq_live_contract_per_employee",
                violation_error_message=_("That employee already has a live contract."),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="contract_end_after_start",
                violation_error_message=_("The end date cannot precede the start date."),
            ),
            # RN-12: un contrato a plazo fijo tiene fecha de fin.
            models.CheckConstraint(
                condition=~models.Q(contract_type=ContractType.FIXED_TERM.value)
                | models.Q(end_date__isnull=False),
                name="contract_fixed_term_has_end",
                violation_error_message=_("A fixed-term contract needs an end date."),
            ),
            # RN-11: uno indefinido no tiene fecha de fin; su final es la baja.
            models.CheckConstraint(
                condition=~models.Q(contract_type=ContractType.INDEFINITE.value)
                | models.Q(end_date__isnull=True),
                name="contract_indefinite_has_no_end",
                violation_error_message=_("An indefinite contract cannot have an end date."),
            ),
            models.CheckConstraint(
                condition=models.Q(probation_end_date__isnull=True)
                | models.Q(probation_end_date__gte=models.F("start_date")),
                name="contract_probation_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(termination_date__isnull=True)
                | models.Q(termination_date__gte=models.F("start_date")),
                name="contract_termination_after_start",
            ),
            # RN-16: TERMINATED lleva fecha y motivo; los demás estados, ninguno.
            models.CheckConstraint(
                condition=(
                    models.Q(status=_TERMINATED, termination_date__isnull=False)
                    & ~models.Q(termination_reason="")
                )
                | (
                    ~models.Q(status=_TERMINATED)
                    & models.Q(termination_date__isnull=True)
                    & models.Q(termination_reason="")
                ),
                name="contract_termination_is_consistent",
                violation_error_message=_(
                    "A terminated contract needs a date and a reason, and only a terminated one."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ContractStatus.values),
                name="contract_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(contract_type__in=ContractType.values),
                name="contract_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(termination_reason="")
                | models.Q(termination_reason__in=TerminationReason.values),
                name="contract_termination_reason_valid",
            ),
        ]
        indexes = [
            # "Contrato vivo del empleado X": se consulta en cada autorización (I-05).
            models.Index(fields=["employee", "status"], name="contract_employee_status_idx"),
            # Proceso de vencimientos (I-06).
            models.Index(fields=["status", "end_date"], name="contract_status_end_idx"),
        ]

    def __str__(self) -> str:
        # Sin importes ni PII: alimenta AuditEvent.object_repr y los logs.
        return f"{self.employee.employee_code} {self.contract_type} {self.start_date.isoformat()}"

    def get_absolute_url(self) -> str:
        return reverse("contracts:detail", args=[self.public_id])

    @property
    def effective_end(self) -> dt.date | None:
        """Último día del vínculo: la baja si la hubo; si no, el fin pactado."""
        return self.termination_date or self.end_date

    def covers(self, day: dt.date) -> bool:
        end = self.effective_end
        return self.start_date <= day and (end is None or day <= end)


class ContractSalary(TimeStampedModel):
    """Historial salarial. Cada fila es un hecho fechado.

    No hay campo `salary` en el contrato: haría imposible registrar un aumento sin
    destruir el valor anterior, una anomalía de actualización con consecuencias
    legales (§C.6). La fila vigente es la de `effective_to` vacío; cerrarla es la
    única modificación admitida.
    """

    contract = models.ForeignKey(
        "contracts.EmploymentContract",
        on_delete=models.PROTECT,
        related_name="salaries",
        verbose_name=_("contract"),
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    currency = models.CharField(
        _("currency"),
        max_length=CURRENCY_CODE_LENGTH,
        default="GTQ",
        validators=[validate_currency_code],
    )
    pay_frequency = models.CharField(
        _("pay frequency"), max_length=20, choices=PayFrequency, default=PayFrequency.MONTHLY
    )
    effective_from = models.DateField(_("effective from"))
    effective_to = models.DateField(
        _("effective to"), null=True, blank=True, help_text=_("Empty means current salary.")
    )
    change_reason = models.CharField(_("reason"), max_length=40, choices=SalaryChangeReason)
    justification = models.CharField(
        _("justification"),
        max_length=300,
        blank=True,
        help_text=_("Required when the amount is outside the salary band of the position."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("registered by"),
    )

    class Meta:
        verbose_name = _("contract salary")
        verbose_name_plural = _("contract salaries")
        ordering = ("-effective_from",)
        # Sin los permisos por defecto: el acceso a importes se concede SOLO con
        # `view_salary`/`change_salary`. Dos permisos de vista para el mismo dato
        # invitarían a conceder el equivocado creyendo que es otra cosa.
        default_permissions = ()
        permissions = [
            ("view_salary", _("Can view salary amounts")),
            ("change_salary", _("Can register salary changes")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "effective_from"],
                name="uniq_salary_per_contract_and_start",
                violation_error_message=_("There is already a salary starting on that date."),
            ),
            # RN-20: un solo salario vigente por contrato.
            models.UniqueConstraint(
                fields=["contract"],
                condition=models.Q(effective_to__isnull=True),
                name="uniq_open_salary_per_contract",
                violation_error_message=_("That contract already has a current salary."),
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="salary_amount_positive",
                violation_error_message=_("The salary must be greater than zero."),
            ),
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="salary_period_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(pay_frequency__in=PayFrequency.values),
                name="salary_pay_frequency_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(change_reason__in=SalaryChangeReason.values),
                name="salary_change_reason_valid",
            ),
        ]
        indexes = [
            # "Salario vigente del contrato X" (I-07).
            models.Index(fields=["contract", "-effective_from"], name="salary_contract_from_idx"),
        ]

    def __str__(self) -> str:
        # SIN importe: `__str__` acaba en logs y en la bitácora.
        return f"{self.contract} from {self.effective_from.isoformat()}"


class Assignment(TimeStampedModel):
    """Ocupación de un puesto durante un período, dentro de un contrato."""

    contract = models.ForeignKey(
        "contracts.EmploymentContract",
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("contract"),
    )
    position = models.ForeignKey(
        "positions.Position",
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("position"),
        help_text=_("The department is derived from the position."),
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(
        _("end date"), null=True, blank=True, help_text=_("Empty means current assignment.")
    )
    is_primary = models.BooleanField(_("primary assignment"), default=True)
    fte = models.DecimalField(
        _("full-time equivalent"),
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text=_("1.00 is full time."),
    )
    assignment_reason = models.CharField(
        _("reason"), max_length=40, choices=AssignmentReason, default=AssignmentReason.INITIAL
    )

    class Meta:
        verbose_name = _("assignment")
        verbose_name_plural = _("assignments")
        ordering = ("-start_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "position", "start_date"],
                name="uniq_assignment",
            ),
            # RN-24: una sola asignación principal abierta por contrato.
            models.UniqueConstraint(
                fields=["contract"],
                condition=models.Q(end_date__isnull=True, is_primary=True),
                name="uniq_open_primary_assignment",
                violation_error_message=_(
                    "That contract already has a current primary assignment."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="assignment_period_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(fte__gt=0) & models.Q(fte__lte=Decimal("1.00")),
                name="assignment_fte_in_range",
                violation_error_message=_("The FTE must be greater than 0 and at most 1."),
            ),
            models.CheckConstraint(
                condition=models.Q(assignment_reason__in=AssignmentReason.values),
                name="assignment_reason_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["contract", "end_date"], name="assignment_contract_end_idx"),
            # Con Position(department), base del alcance de MANAGER (I-09, ADR-011).
            models.Index(fields=["position", "end_date"], name="assignment_position_end_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.position.code} from {self.start_date.isoformat()}"

    @property
    def department(self):
        """Derivado del puesto; nunca almacenado (ADR-011)."""
        return self.position.department

    def covers(self, day: dt.date) -> bool:
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)
