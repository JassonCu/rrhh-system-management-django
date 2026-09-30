"""Formularios de ausencias.

Campos explícitos, nunca ``__all__``. Ninguno expone al empleado: el titular
sale de la sesión o de la URL validada por el selector (§J.4). Las decisiones
(aprobar, rechazar, cancelar) no llevan el estado destino en el formulario: lo
fija la vista, para que nadie lo sustituya en el `POST`.
"""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth.models import AnonymousUser
from django.utils.translation import gettext_lazy as _

from apps.employees.selectors import employees_visible_for
from apps.leave.constants import MAX_ANNUAL_DAYS
from apps.leave.models import LeaveAccrualTier, LeaveRequest, LeaveType
from apps.leave.selectors import types_visible_for

_DATE = {"type": "date"}


class LeaveTypeStepForm(forms.Form):
    """Paso 1 del asistente: qué tipo de ausencia se solicita."""

    leave_type = forms.ModelChoiceField(
        label=_("Leave type"), queryset=LeaveType.objects.none(), empty_label=None
    )

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["leave_type"].queryset = (
            types_visible_for(user if user is not None else AnonymousUser())
            .filter(is_active=True)
            .order_by("name")
        )


class LeaveDatesStepForm(forms.ModelForm):
    """Paso 2: fechas y motivo.

    El motivo es opcional a propósito: puede contener datos de salud y no se
    exige para pedir. Los días hábiles **no** se capturan, los calcula el
    servicio (RN-42): un dato derivado que escribiera la persona sería un hueco.
    """

    class Meta:
        model = LeaveRequest
        fields = ["start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs=_DATE),
            "end_date": forms.DateInput(attrs=_DATE),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "reason": _("Optional. Do not include medical details."),
        }

    def clean(self) -> dict:
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError(
                _("The end date cannot be earlier than the start date."), code="dates_unordered"
            )
        return cleaned


class DecisionForm(forms.Form):
    """Nota de una decisión. Obligatoria al rechazar; la vista lo exige."""

    note = forms.CharField(
        label=_("Note"),
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("The requester will read it."),
    )


class LeaveTypeForm(forms.ModelForm):
    """Catálogo de tipos de ausencia."""

    class Meta:
        model = LeaveType
        fields = [
            "code",
            "name",
            "is_paid",
            "requires_approval",
            "requires_document",
            "allows_negative_balance",
            "default_annual_days",
            "min_notice_days",
            "max_backdating_days",
            "is_sensitive",
            "is_active",
        ]
        help_texts = {
            "is_sensitive": _("Sensitive types are hidden from the team calendar."),
            "default_annual_days": _("Accrued in twelfths, one twelfth per month worked."),
        }

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("min_notice_days") and cleaned.get("max_backdating_days"):
            raise forms.ValidationError(
                _("A type cannot require notice and also allow retroactive registration."),
                code="notice_or_backdating",
            )
        return cleaned

    def clean_default_annual_days(self) -> Decimal:
        days = self.cleaned_data["default_annual_days"]
        if days > MAX_ANNUAL_DAYS:
            raise forms.ValidationError(
                _("That is above the maximum of %(max)s days per year."),
                code="above_maximum",
                params={"max": MAX_ANNUAL_DAYS},
            )
        return days


class AccrualTierForm(forms.ModelForm):
    """Tramo por antigüedad. El tipo sale de la URL, nunca del formulario."""

    class Meta:
        model = LeaveAccrualTier
        fields = ["min_years_of_service", "annual_days"]


class BalanceAdjustmentForm(forms.Form):
    """Corrección manual de saldo. Exige motivo (RN-46: queda asentada)."""

    employee = forms.ModelChoiceField(
        label=_("Employee"), queryset=employees_visible_for(AnonymousUser())
    )
    leave_type = forms.ModelChoiceField(label=_("Leave type"), queryset=LeaveType.objects.none())
    days = forms.DecimalField(
        label=_("Days"),
        max_digits=6,
        decimal_places=2,
        help_text=_("Positive adds to the balance; negative subtracts from it."),
    )
    note = forms.CharField(
        label=_("Reason"),
        max_length=300,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("It is recorded in the ledger and in the audit log with your name."),
    )

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # La propia ficha no se ofrece: nadie ajusta su saldo (lo impone el servicio).
        people = employees_visible_for(user if user is not None else AnonymousUser())
        if user is not None and user.is_authenticated:
            people = people.exclude(user=user)
        self.fields["employee"].queryset = people.select_related("person")
        self.fields["leave_type"].queryset = (
            types_visible_for(user if user is not None else AnonymousUser())
            .filter(is_active=True)
            .order_by("name")
        )

    def clean_days(self) -> Decimal:
        days = self.cleaned_data["days"]
        if days == 0:
            raise forms.ValidationError(
                _("An adjustment of zero days changes nothing."), code="adjustment_needs_days"
            )
        return days
