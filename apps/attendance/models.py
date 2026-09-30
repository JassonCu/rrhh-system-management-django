"""Jornadas, marcajes e incidencias (Fase 5).

Decisiones de modelo que conviene tener a la vista:

- **La tolerancia vive en la jornada** (`WorkSchedule.grace_minutes`), no en una
  constante del código: cada área puede tener la suya y cambiarla es un dato.
- **El total diario no se almacena.** Se calcula agregando segmentos en un
  selector. Guardarlo sería un duplicado que puede divergir del detalle; si el
  volumen lo exige, se materializará después de medir (§B.7).
- **Un marcaje no se edita en silencio**: se corrige y queda el rastro en la
  bitácora, con motivo obligatorio (RN-53).
- **Las horas extra nacen como incidencia abierta**: solo cuentan para pago si
  alguien las aprueba.
"""

from __future__ import annotations

import datetime as dt

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.attendance.constants import (
    DEFAULT_GRACE_MINUTES,
    MAX_GRACE_MINUTES,
    MAX_WEEKLY_HOURS,
    AttendanceSource,
    IncidentStatus,
    IncidentType,
    Weekday,
)
from apps.core.models import TimeStampedModel


class WorkSchedule(TimeStampedModel):
    """Jornada pactada: el patrón contra el que se comparan los marcajes."""

    code = models.CharField(_("code"), max_length=20, unique=True)
    name = models.CharField(_("name"), max_length=80)
    weekly_hours = models.DecimalField(_("weekly hours"), max_digits=5, decimal_places=2)
    grace_minutes = models.PositiveSmallIntegerField(
        _("grace period (minutes)"),
        default=DEFAULT_GRACE_MINUTES,
        help_text=_("Minutes of tolerance before an arrival counts as late."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("work schedule")
        verbose_name_plural = _("work schedules")
        ordering = ("code",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekly_hours__gt=0)
                & models.Q(weekly_hours__lte=MAX_WEEKLY_HOURS),
                name="schedule_weekly_hours_in_range",
                violation_error_message=_("The weekly hours must be between 0 and 168."),
            ),
            models.CheckConstraint(
                condition=models.Q(grace_minutes__lte=MAX_GRACE_MINUTES),
                name="schedule_grace_in_range",
                violation_error_message=_("The grace period cannot exceed 120 minutes."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class WorkScheduleDay(TimeStampedModel):
    """Un día de la jornada.

    Una fila por día en lugar de columnas `monday_start`, `tuesday_start`…: esas
    columnas son un grupo repetitivo disfrazado y rompen 1NF. Los días que no
    aparecen son días de descanso.
    """

    work_schedule = models.ForeignKey(
        "attendance.WorkSchedule",
        # Composición: un día no significa nada sin su jornada. Es la excepción
        # justificada a la regla de no usar CASCADE (§F.1).
        on_delete=models.CASCADE,
        related_name="days",
        verbose_name=_("work schedule"),
    )
    weekday = models.PositiveSmallIntegerField(_("weekday"), choices=Weekday.choices)
    start_time = models.TimeField(_("start time"))
    end_time = models.TimeField(_("end time"))
    break_minutes = models.PositiveSmallIntegerField(_("break (minutes)"), default=0)

    class Meta:
        verbose_name = _("work schedule day")
        verbose_name_plural = _("work schedule days")
        ordering = ("work_schedule", "weekday")
        constraints = [
            models.UniqueConstraint(
                fields=["work_schedule", "weekday"],
                name="uniq_day_per_schedule",
                violation_error_message=_("That schedule already has this weekday."),
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="schedule_day_times_ordered",
                violation_error_message=_("The start time must precede the end time."),
            ),
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0) & models.Q(weekday__lte=6),
                name="schedule_day_weekday_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.work_schedule.code} {self.get_weekday_display()}"

    @property
    def expected_minutes(self) -> int:
        """Minutos de trabajo esperados ese día, descontando el descanso."""
        start = dt.datetime.combine(dt.date.min, self.start_time)
        end = dt.datetime.combine(dt.date.min, self.end_time)
        return int((end - start).total_seconds() // 60) - self.break_minutes


class ScheduleAssignment(TimeStampedModel):
    """Jornada vigente de un contrato, con historial.

    Una columna `work_schedule_id` en el contrato perdería el pasado: para
    recalcular un período antiguo hace falta saber qué jornada regía entonces.
    """

    contract = models.ForeignKey(
        "contracts.EmploymentContract",
        on_delete=models.PROTECT,
        related_name="schedule_assignments",
        verbose_name=_("contract"),
    )
    work_schedule = models.ForeignKey(
        "attendance.WorkSchedule",
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name=_("work schedule"),
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(
        _("end date"), null=True, blank=True, help_text=_("Empty means current schedule.")
    )

    class Meta:
        verbose_name = _("schedule assignment")
        verbose_name_plural = _("schedule assignments")
        ordering = ("-start_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "start_date"],
                name="uniq_schedule_per_contract_and_start",
            ),
            models.UniqueConstraint(
                fields=["contract"],
                condition=models.Q(end_date__isnull=True),
                name="uniq_open_schedule_per_contract",
                violation_error_message=_("That contract already has a current schedule."),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="schedule_assignment_period_ordered",
                violation_error_message=_("The end date cannot precede the start date."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contract_id} → {self.work_schedule.code}"


class AttendanceEntry(TimeStampedModel):
    """Segmento de marcaje: una entrada y su salida.

    Se admiten varios segmentos por día (jornada partida). El total diario no se
    guarda aquí: lo calcula `selectors.worked_minutes`.
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_entries",
        verbose_name=_("employee"),
    )
    work_date = models.DateField(_("work date"))
    check_in_at = models.DateTimeField(_("check in"))
    check_out_at = models.DateTimeField(_("check out"), null=True, blank=True)
    source = models.CharField(
        _("source"), max_length=12, choices=AttendanceSource.choices, default=AttendanceSource.SELF
    )
    registered_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("registered by"),
    )
    note = models.CharField(_("note"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("attendance entry")
        verbose_name_plural = _("attendance entries")
        ordering = ("-work_date", "-check_in_at")
        permissions = [("adjust_attendance", _("Can correct attendance entries"))]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "work_date", "check_in_at"],
                name="uniq_entry_per_employee_and_check_in",
            ),
            # Un solo segmento abierto por persona: marcar dos entradas seguidas
            # es el error más común y la base lo impide (RN-51).
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(check_out_at__isnull=True),
                name="uniq_open_entry_per_employee",
                violation_error_message=_("That person already has an open entry."),
            ),
            models.CheckConstraint(
                condition=models.Q(check_out_at__isnull=True)
                | models.Q(check_in_at__lt=models.F("check_out_at")),
                name="entry_times_ordered",
                violation_error_message=_("The check-out must come after the check-in (RN-50)."),
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=AttendanceSource.values),
                name="entry_source_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "work_date"], name="entry_employee_date_idx"),
            models.Index(fields=["work_date"], name="entry_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.work_date}"

    @property
    def is_open(self) -> bool:
        return self.check_out_at is None

    @property
    def minutes(self) -> int:
        """Minutos trabajados en el segmento; 0 si sigue abierto."""
        if self.check_out_at is None:
            return 0
        return int((self.check_out_at - self.check_in_at).total_seconds() // 60)


class AttendanceIncident(TimeStampedModel):
    """Desvío respecto de la jornada: tardanza, salida temprana, extra…

    Las horas extra nacen `OPEN`: solo cuentan para pago cuando alguien las
    aprueba (`JUSTIFIED`). Una incidencia nunca se borra; se resuelve.
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_incidents",
        verbose_name=_("employee"),
    )
    work_date = models.DateField(_("work date"))
    incident_type = models.CharField(_("type"), max_length=16, choices=IncidentType.choices)
    minutes = models.PositiveIntegerField(_("minutes"), default=0)
    status = models.CharField(
        _("status"), max_length=10, choices=IncidentStatus.choices, default=IncidentStatus.OPEN
    )
    justification = models.CharField(_("justification"), max_length=300, blank=True)
    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("resolved by"),
    )
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)

    class Meta:
        verbose_name = _("attendance incident")
        verbose_name_plural = _("attendance incidents")
        ordering = ("-work_date", "incident_type")
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "work_date", "incident_type"],
                name="uniq_incident_per_employee_date_and_type",
            ),
            models.CheckConstraint(
                condition=models.Q(incident_type__in=IncidentType.values),
                name="incident_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=IncidentStatus.values),
                name="incident_status_valid",
            ),
            # Resolver exige constancia de quién y cuándo (RN-53).
            models.CheckConstraint(
                condition=models.Q(status=IncidentStatus.OPEN, resolved_at__isnull=True)
                | (~models.Q(status=IncidentStatus.OPEN) & models.Q(resolved_at__isnull=False)),
                name="incident_resolution_is_consistent",
                violation_error_message=_("A resolved incident needs the date it was resolved."),
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "work_date"], name="incident_employee_date_idx"),
            models.Index(fields=["status", "work_date"], name="incident_status_date_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_code} {self.work_date} {self.incident_type}"

    @property
    def is_open(self) -> bool:
        return self.status == IncidentStatus.OPEN
