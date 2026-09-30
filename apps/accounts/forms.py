"""Formularios de cuentas.

**Ningún formulario de este módulo expone `is_staff`, `is_superuser` ni
`user_permissions`**, y ninguno usa ``fields = "__all__"`` (regla 39, §J.5). Los
campos se declaran uno a uno, y hay una prueba que recorre todos los formularios
del proyecto para verificarlo.
"""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.accounts.roles import Role

User = get_user_model()


class InviteUserForm(forms.Form):
    """Alta de una cuenta por parte de RRHH.

    No es un `ModelForm` a propósito: el alta no consiste en guardar un modelo
    sino en ejecutar un caso de uso (crear, asignar roles, auditar, enviar la
    invitación). El servicio es quien lo orquesta.
    """

    email = forms.EmailField(
        label=_("Email address"),
        max_length=254,
        help_text=_("The invitation will be sent to this address."),
    )
    roles = forms.MultipleChoiceField(
        label=_("Roles"),
        choices=Role.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=_("A user without roles can sign in but sees nothing."),
    )

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(
                _("An account with that email address already exists."),
                code="duplicate_email",
            )
        return email

    def clean_roles(self) -> list[str]:
        roles = self.cleaned_data.get("roles", [])
        # La incompatibilidad se valida también en el servicio; aquí se adelanta
        # para dar un mensaje en el formulario en lugar de un error genérico.
        if Role.AUDITOR in roles and len(roles) > 1:
            raise forms.ValidationError(
                _("The auditor role cannot be combined with any other role."),
                code="incompatible_roles",
            )
        return list(roles)


class DeactivateUserForm(forms.Form):
    """Baja de una cuenta. El motivo viaja a la bitácora, no al modelo."""

    reason = forms.CharField(
        label=_("Reason"),
        max_length=200,
        required=False,
        help_text=_("Optional. It is recorded in the audit log."),
    )


class ProfileForm(forms.ModelForm):
    """Preferencias que la propia persona puede cambiar.

    El nombre y los datos personales **no** se editan aquí: viven en
    ``employees.Person`` y los gestiona RRHH (Fase 3).
    """

    class Meta:
        model = User
        fields = ["language"]  # explícito: nunca "__all__"
        labels = {"language": _("Preferred language")}
