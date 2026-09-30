"""Vence los contratos vivos cuya fecha de fin ya pasó."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.contracts.services import expire_contracts


class Command(BaseCommand):
    help = "Marca como EXPIRED los contratos vencidos y sincroniza el estado de los empleados."

    def handle(self, *_args: Any, **_options: Any) -> None:
        expired = expire_contracts()
        self.stdout.write(self.style.SUCCESS(f"Contratos vencidos: {expired}."))
