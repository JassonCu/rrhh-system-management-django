"""Formularios de la estructura organizacional.

Campos explícitos, nunca `__all__` (regla 39). El `queryset` de cada
`ModelChoiceField` se acota con el selector del usuario, para que no se pueda
referenciar por POST un objeto que no se puede ver (§J.4).
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.models import Company
from apps.departments.models import Department, DepartmentHeadship
from apps.departments.selectors import departments_visible_for
from apps.employees.selectors import employees_visible_for


class CompanyForm(forms.ModelForm):
    """Alta y edición de la entidad empleadora, fuera del admin (UX-3, D-07)."""

    class Meta:
        model = Company
        fields = ["code", "legal_name", "trade_name", "tax_id", "country", "is_active"]


class HeadshipForm(forms.ModelForm):
    """Nombramiento de jefatura.

    El desplegable se acota con el selector del usuario: no se puede nombrar por
    POST a alguien que no se puede ver (§J.4).
    """

    class Meta:
        model = DepartmentHeadship
        fields = ["employee", "start_date", "appointment_note"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["employee"]
        field.queryset = (
            employees_visible_for(user).select_related("person")
            if user is not None
            else field.queryset.none()
        )


class EndHeadshipForm(forms.Form):
    end_date = forms.DateField(label=_("End date"), widget=forms.DateInput(attrs={"type": "date"}))


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["company", "parent", "code", "name", "cost_center"]

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True)

        parents = departments_visible_for(user) if user else Department.objects.none()
        if self.instance.pk:
            # Un departamento no puede ser su propio padre ni el de un
            # descendiente: se retiran del desplegable además de validarlo en el
            # servicio, para que el error no llegue a producirse.
            from apps.departments.selectors import descendant_ids

            parents = parents.exclude(pk__in=descendant_ids([self.instance.pk]))
        self.fields["parent"].queryset = parents.filter(is_active=True)
        self.fields["parent"].empty_label = _("(root of the organization chart)")
