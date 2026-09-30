"""Ausencias: tipos, derechos, solicitudes y libro de saldos (Fase 6).

Decisiones de modelo que conviene tener a la vista:

- **El saldo no se almacena.** Se suma del libro (`LeaveLedgerEntry`), que es
  append-only: un error se corrige con un asiento de reversa, nunca editando o
  borrando el anterior (RN-46, ADR-015).
- **El tipo declara si es sensible.** Incapacidad y duelo no se muestran al
  equipo: revelan salud o intimidad (decisión de negocio de la Fase 6).
- **Cada cambio de estado deja su transición**, con actor y nota: la pregunta
  «¿quién aprobó esto y cuándo?» tiene que poder responderse años después.
"""

from __future__ import annotations

import uuid
from typing import Any, NoReturn

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.exceptions import DomainError
from apps.core.models import TimeStampedModel
from apps.leave.constants import (
    MAX_ANNUAL_DAYS,
    MAX_BACKDATING_DAYS,
    EntitlementSource,
    LeaveStatus,
    LedgerEntryType,
)


class LeaveType(TimeStampedModel):
    """Catálogo de ausencias: vacaciones, incapacidad, permisos…"""

    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=80)
    is_paid = models.BooleanField(_("paid"), default=True)
    requires_approval = models.BooleanField(_("requires approval"), default=True)
    requires_document = models.BooleanField(
        _("requires document"),
        default=False,
        help_text=_("For example, a medical certificate."),
    )
    allows_negative_balance = models.BooleanField(
        _("allows negative balance"),
        default=False,
        help_text=_("Only for types the company grants in advance."),
    )
    default_annual_days = models.DecimalField(
        _("annual days"),
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_("Days accrued per year. They are granted month by month."),
    )
    min_notice_days = models.PositiveSmallIntegerField(_("minimum notice (days)"), default=0)
    max_backdating_days = models.PositiveSmallIntegerField(
        _("retroactive registration (days)"),
        default=0,
        help_text=_(
            "How many days after it started the leave can still be registered. "
            "0 means it must be requested in advance."
        ),
    )
    is_sensitive = models.BooleanField(
        _("sensitive"),
        default=False,
        help_text=_("The team calendar shows it as a generic absence, without the type."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("leave type")
        verbose_name_plural = _("leave types")
        ordering = ("code",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(default_annual_days__gte=0)
                & models.Q(default_annual_days__lte=MAX_ANNUAL_DAYS),
                name="leave_type_annual_days_in_range",
                violation_error_message=_("The annual days must be between 0 and 60."),
            ),
            models.CheckConstraint(
                condition=models.Q(max_backdating_days__lte=MAX_BACKDATING_DAYS),
                name="leave_type_backdating_in_range",
                violation_error_message=_("Retroactive registration cannot exceed 30 days."),
            ),
            # Un tipo que se reporta después del hecho no puede exigir aviso previo:
            # las dos reglas juntas se contradicen (decisión P-1 de la Fase 6).
            models.CheckConstraint(
                condition=models.Q(min_notice_days=0) | models.Q(max_backdating_days=0),
                name="leave_type_notice_or_backdating",
                violation_error_message=_(
                    "A type cannot require notice and also allow retroactive registration."
                ),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class LeaveAccrualTier(TimeStampedModel):
    """Días por año según la antigüedad: a más años de servicio, más días.

    El tipo guarda los días **base** (el piso legal); cada tramo dice cuántos
    días corresponden desde cierta antigüedad. Que un tramo nunca quede por
    debajo del piso ni por debajo de un tramo menor lo imponen los servicios,
    porque son comparaciones entre filas (ADR-022).
    """

    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="accrual_tiers",
        verbose_name=_("leave type"),
    )
    min_years_of_service = models.PositiveSmallIntegerField(
        _("from years of service"),
        help_text=_("Completed years of service from which this tier applies."),
    )
    annual_days = models.DecimalField(_("days per year"), max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = _("accrual tier")
        verbose_name_plural = _("accrual tiers")
        ordering = ("leave_type", "min_years_of_service")
        constraints = [
            models.UniqueConstraint(
                fields=["leave_type", "min_years_of_service"],
                name="uniq_tier_per_type_and_seniority",
                violation_error_message=_("That type already has a tier for those years."),
            ),
            # El año 0 lo cubren los días base del tipo: un tramo empieza en 1.
            models.CheckConstraint(
                condition=models.Q(min_years_of_service__gte=1),
                name="tier_starts_after_first_year",
                violation_error_message=_("A tier starts at one year of service or more."),
            ),
            models.CheckConstraint(
                condition=models.Q(annual_days__gte=0) & models.Q(annual_days__lte=MAX_ANNUAL_DAYS),
                name="tier_annual_days_in_range",
                violation_error_message=_("The annual days must be between 0 and 60."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.leave_type.code} ≥{self.min_years_of_service}: {self.annual_days}"


class LeaveEntitlement(TimeStampedModel):
    """Derecho devengado en un período.

    Documenta **de dónde salen** los días: un asiento del libro sin su origen
    sería un número sin historia.
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_entitlements",
        verbose_name=_("employee"),
    )
    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="entitlements",
        verbose_name=_("leave type"),
    )
    period_start = models.DateField(_("period start"))
    period_end = models.DateField(_("period end"))
    granted_days = models.DecimalField(_("granted days"), max_digits=6, decimal_places=2)
    source = models.CharField(
        _("source"),
        max_length=10,
        choices=EntitlementSource.choices,
        default=EntitlementSource.ACCRUAL,
    )

    class Meta:
        verbose_name = _("leave entitlement")
        verbose_name_plural = _("leave entitlements")
        ordering = ("-period_start",)
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "leave_type", "period_start"],
                name="uniq_entitlement_per_period",
                violation_error_message=_("That period was already accrued."),
            ),
            models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end")),
                name="entitlement_period_ordered",
                violation_error_message=_("The period start must precede its end."),
            ),
            models.CheckConstraint(
                condition=models.Q(granted_days__gte=0),
                name="entitlement_days_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=EntitlementSource.values),
                name="entitlement_source_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.leave_type.code} {self.period_start}"


class LeaveRequest(TimeStampedModel):
    """Solicitud de ausencia y su máquina de estados (RN-45)."""

    public_id = models.UUIDField(
        _("public ID"),
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text=_("Used in URLs. It does not replace authorization."),
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_requests",
        verbose_name=_("employee"),
    )
    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name=_("leave type"),
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    working_days = models.DecimalField(
        _("working days"),
        max_digits=5,
        decimal_places=2,
        help_text=_("Calculated from the schedule and the public holidays."),
    )
    status = models.CharField(
        _("status"), max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.DRAFT
    )
    reason = models.CharField(_("reason"), max_length=300, blank=True)
    decided_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("decided by"),
    )
    decided_at = models.DateTimeField(_("decided at"), null=True, blank=True)
    decision_note = models.CharField(_("decision note"), max_length=300, blank=True)

    class Meta:
        verbose_name = _("leave request")
        verbose_name_plural = _("leave requests")
        ordering = ("-start_date",)
        permissions = [("approve_leave", _("Can approve or reject leave requests"))]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__lte=models.F("end_date")),
                name="leave_dates_ordered",
                violation_error_message=_("The end date cannot precede the start date."),
            ),
            models.CheckConstraint(
                condition=models.Q(working_days__gt=0),
                name="leave_working_days_positive",
                violation_error_message=_("The request must cover at least one working day."),
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=LeaveStatus.values),
                name="leave_status_valid",
            ),
            # Decidida ⇒ hay constancia de cuándo; pendiente ⇒ todavía no la hay.
            # Una cancelada puede tenerla o no: si se aprobó y luego se canceló,
            # la constancia de la aprobación se conserva (no se reescribe el pasado).
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=[LeaveStatus.APPROVED, LeaveStatus.REJECTED])
                    & models.Q(decided_at__isnull=False)
                )
                | (
                    models.Q(status__in=[LeaveStatus.DRAFT, LeaveStatus.SUBMITTED])
                    & models.Q(decided_at__isnull=True)
                )
                | models.Q(status=LeaveStatus.CANCELLED),
                name="leave_decision_is_consistent",
                violation_error_message=_("A decided request needs the date it was decided."),
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "start_date"], name="leave_employee_start_idx"),
            models.Index(fields=["status", "start_date"], name="leave_status_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.leave_type.code} {self.start_date}"

    @property
    def is_pending(self) -> bool:
        return self.status == LeaveStatus.SUBMITTED

    def covers(self, day) -> bool:
        return self.start_date <= day <= self.end_date


class LeaveRequestTransition(TimeStampedModel):
    """Cada cambio de estado, con su actor. Append-only."""

    request = models.ForeignKey(
        "leave.LeaveRequest",
        on_delete=models.PROTECT,
        related_name="transitions",
        verbose_name=_("leave request"),
    )
    # Vacío en la transición de creación: la solicitud no venía de ningún estado.
    # Registrarla como DRAFT → DRAFT violaría `from_status <> to_status`.
    from_status = models.CharField(
        _("from"), max_length=10, choices=LeaveStatus.choices, blank=True
    )
    to_status = models.CharField(_("to"), max_length=10, choices=LeaveStatus.choices)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("actor"),
    )
    note = models.CharField(_("note"), max_length=300, blank=True)

    class Meta:
        verbose_name = _("leave request transition")
        verbose_name_plural = _("leave request transitions")
        ordering = ("-created_at",)
        default_permissions = ("add", "view")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(from_status__in=[*LeaveStatus.values, ""])
                & models.Q(to_status__in=LeaveStatus.values),
                name="transition_statuses_valid",
            ),
            # Una transición que no cambia nada no es una transición (§B.8).
            models.CheckConstraint(
                condition=~models.Q(from_status=models.F("to_status")),
                name="transition_changes_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.request_id}: {self.from_status} → {self.to_status}"


class LedgerImmutableError(DomainError):
    """Se intentó modificar o borrar un asiento del libro de saldos."""

    default_code = "leave_ledger_is_append_only"


class LeaveLedgerEntryQuerySet(models.QuerySet):
    """Bloquea las escrituras masivas, que saltarían ``Model.save``/``delete``.

    Sin esto, ``LeaveLedgerEntry.objects.filter(...).delete()`` borraría
    asientos sin pasar por la guarda del modelo. Mismo patrón que la bitácora.
    """

    def update(self, **kwargs: Any) -> NoReturn:
        raise LedgerImmutableError(fields=sorted(kwargs))

    def delete(self) -> NoReturn:
        raise LedgerImmutableError(operation="queryset_delete")


class LeaveLedgerEntry(TimeStampedModel):
    """Asiento del libro de saldos. **Nunca se edita ni se borra** (RN-46).

    El saldo de una persona es la suma de sus asientos. Guardar el saldo en una
    columna invitaría a que divergiera del detalle, que es justamente la
    información que permite explicar cómo se llegó a él.
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_ledger",
        verbose_name=_("employee"),
    )
    leave_type = models.ForeignKey(
        "leave.LeaveType",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("leave type"),
    )
    entry_type = models.CharField(_("type"), max_length=12, choices=LedgerEntryType.choices)
    days = models.DecimalField(
        _("days"),
        max_digits=6,
        decimal_places=2,
        help_text=_("Positive adds to the balance; negative consumes it."),
    )
    request = models.ForeignKey(
        "leave.LeaveRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
        verbose_name=_("leave request"),
    )
    entitlement = models.ForeignKey(
        "leave.LeaveEntitlement",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
        verbose_name=_("entitlement"),
    )
    note = models.CharField(_("note"), max_length=300, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("created by"),
    )

    objects = LeaveLedgerEntryQuerySet.as_manager()

    class Meta:
        verbose_name = _("leave ledger entry")
        verbose_name_plural = _("leave ledger entries")
        ordering = ("-created_at",)
        # Sin `change` ni `delete`: el libro es append-only, como la bitácora.
        default_permissions = ("add", "view")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(days=0),
                name="ledger_days_not_zero",
                violation_error_message=_("An entry of zero days explains nothing."),
            ),
            models.CheckConstraint(
                condition=models.Q(entry_type__in=LedgerEntryType.values),
                name="ledger_entry_type_valid",
            ),
            # El signo cuenta la historia: lo que se devenga o se devuelve suma, lo
            # que se consume resta. Un ajuste puede ir en ambos sentidos (§B.8).
            models.CheckConstraint(
                condition=(
                    models.Q(
                        entry_type__in=[LedgerEntryType.ACCRUAL, LedgerEntryType.REVERSAL],
                        days__gt=0,
                    )
                    | models.Q(entry_type=LedgerEntryType.CONSUMPTION, days__lt=0)
                    | models.Q(entry_type=LedgerEntryType.ADJUSTMENT)
                ),
                name="ledger_sign_matches_type",
                violation_error_message=_("The sign of the days does not match the entry type."),
            ),
            # Un consumo o una reversa siempre nacen de una solicitud.
            models.CheckConstraint(
                condition=~models.Q(
                    entry_type__in=[LedgerEntryType.CONSUMPTION, LedgerEntryType.REVERSAL]
                )
                | models.Q(request__isnull=False),
                name="ledger_movement_has_its_request",
                violation_error_message=_("A consumption or reversal needs its request."),
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "leave_type"], name="ledger_employee_type_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.leave_type.code} {self.days}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Impide reescribir un asiento: la corrección es otro asiento (RN-46)."""
        if self.pk is not None:
            raise LedgerImmutableError(operation="update", entry=self.pk)
        super().save(*args, **kwargs)

    def delete(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise LedgerImmutableError(operation="delete", entry=self.pk)
