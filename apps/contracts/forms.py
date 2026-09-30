"""Formularios de la relación laboral.

Campos explícitos, nunca `__all__`. **Ninguno expone `employee`, `status`,
`effective_to`, `end_date` de asignación ni `created_by`**: el titular lo fija la
URL validada por el selector, el estado cambia por casos de uso y los cierres de
período los calcula el servicio. Un campo de estado editable sería una forma de
saltarse la máquina de estados manipulando el POST.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.contracts.constants import TerminationReason
from apps.contracts.models import Assignment, ContractSalary, EmploymentContract
from apps.core.models import Company
from apps.positions.selectors import positions_visible_for

_DATE = {"type": "date"}


class ContractForm(forms.ModelForm):
    class Meta:
        model = EmploymentContract
        fields = [
            "company",
            "contract_type",
            "start_date",
            "end_date",
            "probation_end_date",
            "signed_on",
            "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs=_DATE),
            "end_date": forms.DateInput(attrs=_DATE),
            "probation_end_date": forms.DateInput(attrs=_DATE),
            "signed_on": forms.DateInput(attrs=_DATE),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True)


class SalaryForm(forms.ModelForm):
    class Meta:
        model = ContractSalary
        fields = [
            "amount",
            "currency",
            "pay_frequency",
            "effective_from",
            "change_reason",
            "justification",
        ]
        widgets = {"effective_from": forms.DateInput(attrs=_DATE)}


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = Assignment
        fields = ["position", "start_date", "fte", "is_primary", "assignment_reason"]
        widgets = {"start_date": forms.DateInput(attrs=_DATE)}

    def __init__(self, *args, user=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # El desplegable se acota con el selector del usuario: no se puede asignar
        # por POST un puesto que no se puede ver (§J.4).
        positions = positions_visible_for(user) if user is not None else None
        field = self.fields["position"]
        field.queryset = (
            positions.filter(is_active=True) if positions is not None else field.queryset.none()
        )

        # ADR-011: primero el área, luego el puesto. Los puestos se agrupan por
        # departamento con <optgroup>, así que la elección es manejable **sin**
        # JavaScript; main.js añade además un filtro por área.
        grouped: dict[str, list[tuple[int, str]]] = {}
        for position in field.queryset.select_related("department").order_by(
            "department__name", "title"
        ):
            grouped.setdefault(position.department.name, []).append((position.pk, position.title))
        field.choices = [("", "---------"), *grouped.items()]
        field.widget.attrs["data-grouped-select"] = _("Department")
        field.widget.attrs["data-grouped-all"] = _("All departments")


class EndAssignmentForm(forms.Form):
    end_date = forms.DateField(label=_("End date"), widget=forms.DateInput(attrs=_DATE))


class TerminateContractForm(forms.Form):
    """Baja de un contrato. No es un `ModelForm`: es un caso de uso."""

    termination_date = forms.DateField(
        label=_("Termination date"), widget=forms.DateInput(attrs=_DATE)
    )
    termination_reason = forms.ChoiceField(label=_("Reason"), choices=TerminationReason.choices)
