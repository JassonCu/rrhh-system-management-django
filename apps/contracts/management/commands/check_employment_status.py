"""Verifica que el estado laboral de cada empleado coincide con sus contratos."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.contracts.selectors import find_status_inconsistencies


class Command(BaseCommand):
    help = "Falla si algún empleado tiene un estado laboral incoherente con sus contratos (RN-18)."

    def handle(self, *_args: Any, **_options: Any) -> None:
        problems = find_status_inconsistencies()
        if problems:
            for problem in problems:
                code, actual = problem["employee_code"], problem["actual"]
                self.stderr.write(f"{code}: {actual} (esperado {problem['expected']})")
            raise CommandError(f"{len(problems)} empleados con estado incoherente.")
        self.stdout.write(self.style.SUCCESS("Estados laborales coherentes con los contratos."))
