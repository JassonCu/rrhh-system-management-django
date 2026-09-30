"""Prevención de *mass assignment* en TODOS los formularios del proyecto (§J.5).

No se revisa una muestra: se recorren todos los `ModelForm` definidos en `apps/`.
Un formulario nuevo que exponga `is_superuser` —o que use `fields = "__all__"`—
hace fallar la suite en el mismo PR que lo introduce.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from django.forms import ModelForm

import apps

#: Campos que jamás deben ser editables desde un formulario de la aplicación.
#: Exponer cualquiera de ellos es escalada de privilegios directa.
FORBIDDEN_FIELDS = frozenset(
    {
        "is_superuser",
        "is_staff",
        "groups",
        "user_permissions",
        "password",
        "last_login",
    }
)

#: FKs de propiedad: si un formulario las expone, el usuario puede reasignar el
#: objeto a otra persona manipulando el POST.
OWNERSHIP_FIELDS = frozenset({"user", "employee", "person", "actor", "uploaded_by", "created_by"})


def iter_model_forms() -> list[type[ModelForm]]:
    """Descubre todos los `ModelForm` declarados bajo `apps/`."""
    found: list[type[ModelForm]] = []
    for module_info in pkgutil.walk_packages(apps.__path__, prefix="apps."):
        if not module_info.name.endswith(".forms"):
            continue
        module = importlib.import_module(module_info.name)
        for attribute in vars(module).values():
            if (
                isinstance(attribute, type)
                and issubclass(attribute, ModelForm)
                and attribute is not ModelForm
                and attribute.__module__ == module_info.name
            ):
                found.append(attribute)
    return found


MODEL_FORMS = iter_model_forms()


@pytest.mark.security
def test_there_are_forms_to_inspect() -> None:
    """Si el descubrimiento fallara, las demás pruebas pasarían en vacío."""
    assert MODEL_FORMS, "No se descubrió ningún ModelForm; revisa iter_model_forms()"


@pytest.mark.security
@pytest.mark.parametrize("form_class", MODEL_FORMS, ids=lambda c: c.__name__)
def test_no_form_uses_all_fields(form_class: type[ModelForm]) -> None:
    """`fields = "__all__"` expone cualquier campo que se añada en el futuro."""
    meta = form_class._meta
    assert meta.fields is not None, (
        f"{form_class.__name__} no declara `fields`: usaría todos los campos del modelo."
    )
    assert meta.fields != "__all__", f"{form_class.__name__} usa fields='__all__' (regla 39)."


@pytest.mark.security
@pytest.mark.parametrize("form_class", MODEL_FORMS, ids=lambda c: c.__name__)
def test_no_form_exposes_privilege_fields(form_class: type[ModelForm]) -> None:
    declared = set(form_class._meta.fields or [])
    leaked = declared & FORBIDDEN_FIELDS
    assert not leaked, f"{form_class.__name__} expone campos de privilegio: {sorted(leaked)}"


#: Excepciones **nominales** a la regla de FKs de propiedad.
#:
#: `HeadshipForm` nombra a la jefatura de un departamento: elegir a la persona es
#: justamente la operación. El dueño del registro —el departamento— sale de la
#: URL validada por el selector, nunca del POST, y el desplegable se acota con
#: `employees_visible_for`. Lo fija, en `departments`,
#: `test_the_appointment_form_only_offers_visible_people`.
OWNERSHIP_EXEMPTIONS: dict[str, set[str]] = {"HeadshipForm": {"employee"}}


@pytest.mark.security
@pytest.mark.parametrize("form_class", MODEL_FORMS, ids=lambda c: c.__name__)
def test_no_form_exposes_ownership_fields(form_class: type[ModelForm]) -> None:
    """Reasignar el dueño por POST es la vía clásica de acceso a datos ajenos."""
    declared = set(form_class._meta.fields or [])
    allowed = OWNERSHIP_EXEMPTIONS.get(form_class.__name__, set())
    leaked = (declared & OWNERSHIP_FIELDS) - allowed
    assert not leaked, (
        f"{form_class.__name__} expone FKs de propiedad {sorted(leaked)}. "
        "El dueño lo fija el servicio, no el formulario."
    )


@pytest.mark.security
@pytest.mark.django_db
def test_privilege_fields_cannot_be_set_through_the_profile_form(make_user) -> None:
    """Prueba de extremo a extremo: enviar el campo prohibido no lo cambia."""
    from apps.accounts.forms import ProfileForm
    from apps.accounts.roles import Role

    account = make_user("escalada@example.com", Role.EMPLOYEE)
    form = ProfileForm(
        data={"language": "en", "is_superuser": "true", "is_staff": "true"},
        instance=account,
    )

    assert form.is_valid()
    form.save()
    account.refresh_from_db()

    assert account.is_superuser is False
    assert account.is_staff is False
    assert account.language == "en"
