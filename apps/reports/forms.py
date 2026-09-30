"""Filtros de los reportes.

El rango de fechas se acota a propósito: un reporte sin límite es una forma
cómoda de sacar la base entera, y además tumba la pantalla. El desplegable de
departamentos se arma con el selector con alcance, así que una jefatura solo
puede filtrar por lo que ya puede ver.
"""

from __future__ import annotations

import datetime as dt

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.departments.selectors import departments_visible_for
from apps.reports.builders import Filters
from apps.reports.constants import MAX_RANGE_DAYS

_DATE = {"type": "date"}

#: Ventana por defecto: los últimos 30 días.
DEFAULT_DAYS = 30


class ReportFilterForm(forms.Form):
    date_from = forms.DateField(label=_("From"), widget=forms.DateInput(attrs=_DATE))
    date_to = forms.DateField(label=_("To"), widget=forms.DateInput(attrs=_DATE))
    department = forms.ModelChoiceField(
        label=_("Department"),
        queryset=None,
        required=False,
        empty_label=_("All within my scope"),
    )

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = departments_visible_for(user)
        today = timezone.localdate()
        self.fields["date_from"].initial = today - dt.timedelta(days=DEFAULT_DAYS)
        self.fields["date_to"].initial = today

    def clean(self) -> dict:
        cleaned = super().clean()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and end:
            if end < start:
                raise forms.ValidationError(
                    _("The end date cannot be earlier than the start date."),
                    code="dates_unordered",
                )
            if (end - start).days + 1 > MAX_RANGE_DAYS:  # el rango es inclusivo
                raise forms.ValidationError(
                    _("The range cannot exceed %(days)s days."),
                    code="range_too_long",
                    params={"days": MAX_RANGE_DAYS},
                )
        return cleaned

    def as_filters(self) -> Filters:
        return Filters(
            date_from=self.cleaned_data["date_from"],
            date_to=self.cleaned_data["date_to"],
            department=self.cleaned_data.get("department"),
        )
