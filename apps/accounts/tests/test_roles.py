"""Roles y permisos: la declaración de `roles.py` es la fuente de verdad."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission

from apps.accounts.roles import NEVER_GRANTED, ROLE_PERMISSIONS, Role
from apps.accounts.roles_sync import apply_roles, resolve_permissions

pytestmark = pytest.mark.django_db


def test_every_role_has_its_group() -> None:
    """El `post_migrate` los crea; si faltara alguno, nadie podría tenerlo."""
    existing = set(Group.objects.values_list("name", flat=True))
    assert set(Role.values) <= existing


def test_sync_is_idempotent() -> None:
    """Ejecutarlo dos veces no debe cambiar nada la segunda."""
    apply_roles(ROLE_PERMISSIONS)
    created, updated = apply_roles(ROLE_PERMISSIONS)
    assert (created, updated) == (0, 0)


def test_sync_removes_permissions_no_longer_declared() -> None:
    """Una declaración que solo sabe añadir no es una fuente de verdad."""
    group = Group.objects.get(name=Role.EMPLOYEE)
    intruder = Permission.objects.get(codename="add_holiday")
    group.permissions.add(intruder)

    apply_roles(ROLE_PERMISSIONS)

    assert intruder not in group.permissions.all()


def test_declared_permissions_all_exist() -> None:
    """Una entrada con errata concedería menos de lo que aparenta, en silencio."""
    missing_by_role = {}
    for role, codenames in ROLE_PERMISSIONS.items():
        _resolved, missing = resolve_permissions(codenames)
        if missing:
            missing_by_role[role] = missing
    assert missing_by_role == {}


@pytest.mark.security
def test_forbidden_permissions_are_never_granted() -> None:
    """Se comprueba sobre el estado real de la base, no sobre la declaración."""
    granted = {
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in Permission.objects.filter(group__isnull=False).select_related(
            "content_type"
        )
    }
    assert not (granted & NEVER_GRANTED), (
        f"Permisos prohibidos concedidos: {granted & NEVER_GRANTED}"
    )


@pytest.mark.security
def test_auditor_has_no_write_permission() -> None:
    """Separación de funciones: el auditor lee, no escribe."""
    auditor_group = Group.objects.get(name=Role.AUDITOR)
    codenames = set(auditor_group.permissions.values_list("codename", flat=True))
    writes = {name for name in codenames if name.startswith(("add_", "change_", "delete_"))}
    assert writes == set()


@pytest.mark.security
def test_only_hr_admin_can_manage_users() -> None:
    groups = Group.objects.filter(permissions__codename="manage_users").values_list(
        "name", flat=True
    )
    assert set(groups) == {Role.HR_ADMIN}


@pytest.mark.security
def test_only_auditor_reads_the_audit_log() -> None:
    """Quien opera el sistema no debe poder revisar el registro que lo vigila."""
    groups = Group.objects.filter(permissions__codename="view_audit_log").values_list(
        "name", flat=True
    )
    assert set(groups) == {Role.AUDITOR}


@pytest.mark.security
def test_superadmin_group_carries_no_explicit_permissions() -> None:
    """Su capacidad viene de `is_superuser`, no de permisos acumulados."""
    group = Group.objects.get(name=Role.SUPERADMIN)
    assert group.permissions.count() == 0


def test_sync_command_runs() -> None:
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("sync_roles", stdout=out)
    assert "Roles sincronizados" in out.getvalue()
