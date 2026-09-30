"""Catálogos de asistencia.

Los **valores** son ASCII estable y nunca se traducen: entran en consultas,
filtros y reportes (§O.3.1). Solo se traduce la etiqueta.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Weekday(models.IntegerChoices):
    """Lunes = 0, como `date.weekday()`: evita conversiones en cada cálculo."""

    MONDAY = 0, _("Monday")
    TUESDAY = 1, _("Tuesday")
    WEDNESDAY = 2, _("Wednesday")
    THURSDAY = 3, _("Thursday")
    FRIDAY = 4, _("Friday")
    SATURDAY = 5, _("Saturday")
    SUNDAY = 6, _("Sunday")


class AttendanceSource(models.TextChoices):
    """Quién originó el marcaje. Responde "¿de dónde salió este dato?"."""

    SELF = "SELF", _("Self-service")
    SUPERVISOR = "SUPERVISOR", _("Registered by the manager")
    HR = "HR", _("Registered by HR")
    DEVICE = "DEVICE", _("Time clock")
    IMPORT = "IMPORT", _("Imported")


class IncidentType(models.TextChoices):
    LATE = "LATE", _("Late arrival")
    EARLY_LEAVE = "EARLY_LEAVE", _("Early leave")
    ABSENCE = "ABSENCE", _("Absence")
    OVERTIME = "OVERTIME", _("Overtime")
    MISSING_PUNCH = "MISSING_PUNCH", _("Missing punch")


class IncidentStatus(models.TextChoices):
    OPEN = "OPEN", _("Open")
    JUSTIFIED = "JUSTIFIED", _("Justified")
    REJECTED = "REJECTED", _("Rejected")


#: Tolerancia por defecto al crear una jornada, en minutos.
#:
#: Es un valor **por jornada** y no una constante del sistema: producción y
#: oficina no tienen por qué compartir criterio, y cambiarlo no debe exigir un
#: despliegue (decisión de negocio, Fase 5).
DEFAULT_GRACE_MINUTES = 10

#: Tope de tolerancia. Más allá, la jornada deja de significar nada.
MAX_GRACE_MINUTES = 120

#: Horas semanales máximas que admite una jornada (7 × 24).
MAX_WEEKLY_HOURS = 168

#: Duración máxima de un segmento de marcaje. Un segmento más largo es casi
#: siempre una salida sin marcar, no una jornada real.
MAX_SEGMENT_HOURS = 16

#: Incidencias que el exceso o el defecto de tiempo genera automáticamente. Las
#: horas extra nacen **abiertas**: solo cuentan para pago si alguien las aprueba
#: (decisión de negocio, Fase 5).
AUTOMATIC_INCIDENTS = (IncidentType.LATE, IncidentType.EARLY_LEAVE, IncidentType.OVERTIME)
