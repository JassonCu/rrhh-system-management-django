"""Cierra el día de asistencia: determina ausencias y salidas tempranas.

Se ejecuta una vez al día, **después** de que termine la jornada. Antes de eso
no se puede saber si alguien se fue temprano o solo salió a almorzar.

Es idempotente: repetirlo no duplica incidencias ni toca las ya resueltas.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.attendance.services import close_day
from apps.contracts.selectors import live_contracts_on


class Command(BaseCommand):
    help = "Cierra el día de asistencia y abre las incidencias de ausencia y salida temprana."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--date",
            help="Día a cerrar en formato AAAA-MM-DD. Por omisión, ayer.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        raw = options.get("date")
        day = dt.date.fromisoformat(raw) if raw else timezone.localdate() - dt.timedelta(days=1)

        closed = 0
        for contract in live_contracts_on(day):
            close_day(employee=contract.employee, work_date=day)
            closed += 1

        self.stdout.write(self.style.SUCCESS(f"Día {day} cerrado para {closed} personas."))
