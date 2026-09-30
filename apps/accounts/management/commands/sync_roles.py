"""Sincroniza los grupos de roles con la declaración de ``roles.py``."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.roles import ROLE_PERMISSIONS
from apps.accounts.roles_sync import apply_roles


class Command(BaseCommand):
    help = "Crea o actualiza los grupos de roles y sus permisos (idempotente)."

    def handle(self, *_args: Any, **_options: Any) -> None:
        created, updated = apply_roles(ROLE_PERMISSIONS)
        self.stdout.write(
            self.style.SUCCESS(f"Roles sincronizados: {created} creados, {updated} actualizados.")
        )
