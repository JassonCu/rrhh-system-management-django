"""Formularios de personas y empleados.

Campos explícitos, nunca `__all__`. **Ningún formulario expone `user`**: vincular
una cuenta a un empleado es una operación de RRHH con su propio servicio, no un
desplegable que se pueda manipular por POST (§J.5).
"""

from __future__ import annotations

from django import forms

from apps.employees.models import EmergencyContact, Employee, IdentityDocument, Person


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "first_name",
            "middle_name",
            "last_name",
            "second_last_name",
            "birth_date",
            "gender",
            "marital_status",
            "nationality",
        ]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"})}


class EmployeeForm(forms.ModelForm):
    """Datos laborales básicos.

    Sin `user`, sin `employment_status` y sin `termination_date`: el estado se
    cambia desde `contracts.services` al activar o terminar un contrato (RN-18).
    """

    class Meta:
        model = Employee
        fields = ["employee_code", "hire_date"]
        widgets = {"hire_date": forms.DateInput(attrs={"type": "date"})}


class IdentityDocumentForm(forms.ModelForm):
    class Meta:
        model = IdentityDocument
        fields = [
            "document_type",
            "number",
            "issuing_country",
            "issued_on",
            "expires_on",
            "is_primary",
        ]
        widgets = {
            "issued_on": forms.DateInput(attrs={"type": "date"}),
            "expires_on": forms.DateInput(attrs={"type": "date"}),
        }


class EmergencyContactForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        fields = ["full_name", "relationship", "phone", "alternate_phone", "priority"]
