"""Comprobaciones de salud del proyecto que fallan ruidosamente en CI."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations() -> None:
    """Un modelo cambiado sin su migración rompe el despliegue, no el desarrollo."""
    out = StringIO()
    try:
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
    except SystemExit as exc:  # pragma: no cover - solo cuando faltan migraciones
        pytest.fail(f"Faltan migraciones por generar:\n{out.getvalue()}")
        raise exc


@pytest.mark.django_db  # los checks del sistema incluyen comprobaciones de base
def test_django_system_checks_pass() -> None:
    call_command("check", stdout=StringIO(), stderr=StringIO())
