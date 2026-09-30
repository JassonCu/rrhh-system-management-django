"""Devenga el mes de ausencias para quienes tienen contrato vivo.

El negocio eligió devengo **proporcional mensual**: cada mes trabajado suma una
doceava parte de los días anuales que correspondan según la antigüedad. Este
comando se ejecuta una vez al mes; repetirlo no duplica nada, porque el período
tiene índice único.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Q
from django.utils import timezone

from apps.contracts.selectors import live_contracts_on
from apps.leave.models import LeaveType
from apps.leave.services import accrue_month


class Command(BaseCommand):
    help = "Devenga el mes de ausencias (proporcional) para cada contrato vivo."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--month",
            help="Mes a devengar en formato AAAA-MM. Por omisión, el mes en curso.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        raw = options.get("month")
        today = timezone.localdate()
        month_start = dt.date.fromisoformat(f"{raw}-01") if raw else today.replace(day=1)

        # También los tipos sin días base pero con tramos por antigüedad.
        types = list(
            LeaveType.objects.filter(is_active=True)
            .filter(Q(default_annual_days__gt=0) | Q(accrual_tiers__isnull=False))
            .distinct()
        )
        accrued = 0
        for contract in live_contracts_on(month_start):
            for leave_type in types:
                if accrue_month(
                    employee=contract.employee, leave_type=leave_type, month_start=month_start
                ):
                    accrued += 1

        self.stdout.write(
            self.style.SUCCESS(f"Devengo de {month_start:%Y-%m}: {accrued} derechos asentados.")
        )
