"""Modelo de usuario: identidad por correo, sin datos de RRHH."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import translation

User = get_user_model()
pytestmark = pytest.mark.django_db


def test_email_is_normalized_to_lowercase() -> None:
    user = User.objects.create_user(email="  Jefe@Example.COM ", password="Segura-12345678")
    assert user.email == "jefe@example.com"


def test_email_uniqueness_is_case_insensitive_thanks_to_normalization() -> None:
    User.objects.create_user(email="jefe@example.com", password="Segura-12345678")
    with pytest.raises((IntegrityError, ValidationError)):
        User.objects.create_user(email="JEFE@EXAMPLE.COM", password="Segura-12345678")


def test_email_is_required() -> None:
    # El mensaje se traduce: se fija el idioma para comprobar el mensaje en sí,
    # no el catálogo (que tiene su propia prueba).
    with translation.override("en"), pytest.raises(ValueError, match="email"):
        User.objects.create_user(email="", password="Segura-12345678")


def test_password_is_hashed_never_stored_in_clear() -> None:
    raw = "Segura-12345678"
    user = User.objects.create_user(email="a@example.com", password=raw)
    assert user.password != raw
    assert user.check_password(raw)


def test_regular_user_has_no_privileges() -> None:
    user = User.objects.create_user(email="a@example.com", password="Segura-12345678")
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser


def test_superuser_flags() -> None:
    admin = User.objects.create_superuser(email="root@example.com", password="Segura-12345678")
    assert admin.is_staff
    assert admin.is_superuser


@pytest.mark.parametrize(
    ("field", "value"),
    [("is_staff", False), ("is_superuser", False)],
)
def test_superuser_requires_both_flags(field: str, value: bool) -> None:
    with translation.override("en"), pytest.raises(ValueError, match="Superuser"):
        User.objects.create_superuser(
            email="root@example.com", password="Segura-12345678", **{field: value}
        )


def test_default_language_comes_from_settings(settings) -> None:
    user = User.objects.create_user(email="a@example.com", password="Segura-12345678")
    assert user.language == settings.LANGUAGE_CODE


def test_str_is_not_translated() -> None:
    user = User.objects.create_user(email="a@example.com", password="Segura-12345678")
    with translation.override("en"):
        english = str(user)
    with translation.override("es-gt"):
        spanish = str(user)
    assert english == spanish == "a@example.com"


def test_user_has_no_hr_fields() -> None:
    """La identidad civil vive en employees.Person, no aquí (§A.2.6)."""
    field_names = {f.name for f in User._meta.get_fields()}
    assert not {"first_name", "last_name", "phone", "birth_date"} & field_names
