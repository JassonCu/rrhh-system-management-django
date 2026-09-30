"""Formularios de asistencia.

Campos explícitos, nunca `__all__`. Ninguno expone el empleado: el titular sale
de la URL validada por el selector o de la sesión (§J.4). El marcaje no tiene
formulario: es un `POST` sin datos, porque el sistema ya sabe qué toca.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.attendance.constants import DEFAULT_GRACE_MINUTES, IncidentStatus, Weekday
from apps.attendance.models import ScheduleAssignment, WorkSchedule
from apps.attendance.selectors import schedules_visible_for

_DATETIME = {"type": "datetime-local"}
_TIME = {"type": "time"}
_DATE = {"type": "date"}


class AdjustEntryForm(forms.Form):
    """Corrección de un marcaje. El motivo es obligatorio (RN-53)."""

    check_in_at = forms.DateTimeField(
        label=_("Check in"), widget=forms.DateTimeInput(attrs=_DATETIME)
    )
    check_out_at = forms.DateTimeField(
        label=_("Check out"), required=False, widget=forms.DateTimeInput(attrs=_DATETIME)
    )
    reason = forms.CharField(
        label=_("Reason"),
        max_length=200,
        help_text=_("It is recorded in the audit log with your name."),
    )


class ResolveIncidentForm(forms.Form):
    """Justificar o rechazar. Aprobar horas extra es justificar su incidencia."""

    status = forms.ChoiceField(
        label=_("Decision"),
        choices=[
            (IncidentStatus.JUSTIFIED, _("Justify")),
            (IncidentStatus.REJECTED, _("Reject")),
        ],
    )
    justification = forms.CharField(
        label=_("Justification"),
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class WorkScheduleForm(forms.ModelForm):
    """Alta de una jornada.

    Los días se capturan con un horario común: es el caso real en oficina y
    producción. Una jornada con horarios distintos por día se arma después
    editando sus días, no complicando este formulario.
    """

    weekdays = forms.TypedMultipleChoiceField(
        label=_("Working days"),
        choices=Weekday.choices,
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
    )
    start_time = forms.TimeField(label=_("Start time"), widget=forms.TimeInput(attrs=_TIME))
    end_time = forms.TimeField(label=_("End time"), widget=forms.TimeInput(attrs=_TIME))
    break_minutes = forms.IntegerField(label=_("Break (minutes)"), min_value=0, initial=60)

    class Meta:
        model = WorkSchedule
        fields = ["code", "name", "weekly_hours", "grace_minutes", "is_active"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["grace_minutes"].initial = DEFAULT_GRACE_MINUTES

    def clean(self) -> dict:
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and start >= end:
            raise forms.ValidationError(
                _("The start time must precede the end time."), code="times_unordered"
            )
        return cleaned

    def day_rows(self) -> list[dict]:
        """Los días tal como los espera `services.create_schedule`."""
        return [
            {
                "weekday": weekday,
                "start_time": self.cleaned_data["start_time"],
                "end_time": self.cleaned_data["end_time"],
                "break_minutes": self.cleaned_data["break_minutes"],
            }
            for weekday in self.cleaned_data["weekdays"]
        ]


class ScheduleAssignmentForm(forms.ModelForm):
    """Asigna una jornada a un contrato. El contrato sale de la URL."""

    class Meta:
        model = ScheduleAssignment
        fields = ["work_schedule", "start_date"]
        widgets = {"start_date": forms.DateInput(attrs=_DATE)}

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["work_schedule"]
        field.queryset = (
            schedules_visible_for(user).filter(is_active=True)
            if user is not None
            else field.queryset.none()
        )
