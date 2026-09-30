"""Carga datos de demostración para ver el sistema funcionando.

**No hace inserciones crudas.** Todo pasa por los servicios de cada app, igual
que si lo hubiera capturado una persona: los contratos se activan con su salario
y su puesto, los marcajes detectan tardanzas, las ausencias descuentan saldo y
cada operación deja su evento en la bitácora. Datos que no respetaran las
invariantes no servirían para probar nada.

Por eso este comando **no importa modelos de otras apps**: consume su interfaz
pública, como cualquier otro código del sistema (ADR-001, ADR-009). La app
`demo` solo se instala en desarrollo.

Dos salvaguardas:

- **Se niega a ejecutarse fuera de desarrollo** (`DEBUG = False`), porque
  inventa personas y contratos.
- **No duplica**: si la organización de demostración ya existe, no hace nada.

Las cuentas de demostración se crean **sin contraseña utilizable**. Para entrar
con una de ellas, fíjela usted:

    python manage.py changepassword ana.lopez@ceiba.test
"""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.accounts.constants import Role
from apps.attendance import services as attendance_services
from apps.attendance.constants import Weekday
from apps.contracts import services as contract_services
from apps.core.models import Company, Holiday
from apps.departments import services as department_services
from apps.documents import services as document_services
from apps.employees.services import create_employee
from apps.leave import services as leave_services
from apps.positions import services as position_services

#: Código de la empresa de demostración: también es la marca de «ya cargado».
DEMO_COMPANY = "CEIBA"

#: Un PDF mínimo pero válido: el expediente necesita algo que abrir.
DEMO_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

#: Personas inventadas. Nombres guatemaltecos corrientes, ningún dato real.
PEOPLE: list[dict[str, Any]] = [
    {"first": "Ana Lucía", "last": "López", "second": "Morales", "role": "HR", "salary": "12500"},
    {"first": "Carlos", "last": "Mejía", "second": "Ruano", "role": "ANALYST", "salary": "8200"},
    {
        "first": "María José",
        "last": "Sandoval",
        "second": "Pérez",
        "role": "LEAD",
        "salary": "18500",
    },
    {"first": "Diego", "last": "Ramírez", "second": "Castillo", "role": "DEV", "salary": "14000"},
    {"first": "Sofía", "last": "Gutiérrez", "second": "Alvarado", "role": "DEV", "salary": "13200"},
    {
        "first": "Luis Fernando",
        "last": "Arriaga",
        "second": "Solís",
        "role": "JUNIOR",
        "salary": "8900",
    },
    {
        "first": "Gabriela",
        "last": "Hernández",
        "second": "Ortiz",
        "role": "SALES_LEAD",
        "salary": "16000",
    },
    {"first": "Pablo", "last": "Estrada", "second": "Chacón", "role": "SELLER", "salary": "9500"},
    {"first": "Andrea", "last": "Molina", "second": "Girón", "role": "SELLER", "salary": "9200"},
    {
        "first": "Rodrigo",
        "last": "Barrios",
        "second": "Quiñónez",
        "role": "SELLER",
        "salary": "8800",
    },
    {"first": "Claudia", "last": "Ixcot", "second": "Tzunún", "role": "ANALYST", "salary": "8600"},
    {
        "first": "Jorge",
        "last": "Velásquez",
        "second": "Marroquín",
        "role": "DEV",
        "salary": "13800",
    },
]

#: Puesto → (área, título, grado, banda salarial, ¿jefatura?, rol de la cuenta).
POSITIONS: dict[str, tuple[str, str, str, int, int, bool, str]] = {
    "HR": ("RRHH", "Jefatura de Recursos Humanos", "G08", 10000, 20000, True, Role.HR_ADMIN),
    "ANALYST": ("RRHH", "Analista de Recursos Humanos", "G05", 7000, 11000, False, Role.EMPLOYEE),
    "LEAD": ("TI", "Jefatura de Tecnología", "G08", 10000, 20000, True, Role.MANAGER),
    "DEV": ("TI", "Desarrollador", "G06", 9000, 16000, False, Role.EMPLOYEE),
    "JUNIOR": ("TI", "Desarrollador junior", "G04", 6000, 10000, False, Role.EMPLOYEE),
    "SALES_LEAD": ("VENTAS", "Jefatura de Ventas", "G08", 10000, 20000, True, Role.MANAGER),
    "SELLER": ("VENTAS", "Ejecutivo de ventas", "G05", 7000, 11000, False, Role.EMPLOYEE),
}

AREAS = {"RRHH": "Recursos Humanos", "TI": "Tecnología", "VENTAS": "Ventas"}

ACCENTS = str.maketrans("áéíóúñ", "aeioun")


class Command(BaseCommand):
    help = "Carga datos de demostración (solo en desarrollo)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--attendance-days",
            type=int,
            default=10,
            help="Días naturales hacia atrás en los que se generan marcajes. 0 los omite.",
        )
        parser.add_argument(
            "--people",
            type=int,
            default=len(PEOPLE),
            help="Cuántas personas crear. Menos personas, organización más pequeña.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError(
                "Este comando inventa personas y contratos: solo se ejecuta con DEBUG=True."
            )
        if Company.objects.filter(code=DEMO_COMPANY).exists():
            self.stdout.write(
                self.style.WARNING(
                    "Los datos de demostración ya están cargados: no se toca nada.\n"
                    "Para empezar de cero: borre db.sqlite3, aplique migraciones y "
                    "vuelva a ejecutar este comando."
                )
            )
            return

        with transaction.atomic():
            company = self._company()
            areas = self._areas(company)
            positions = self._positions(areas)
            schedule = self._schedule()
            self._holidays(company)
            employees = self._employees(company, positions, schedule, options["people"])
            self._headships(areas, employees)
            self._leave(employees)
            self._documents(employees)

        counts = {"empleados": len(employees)}
        if options["attendance_days"]:
            # Fuera de la transacción: cada marcaje evalúa su día.
            counts["marcajes"] = self._attendance(employees, options["attendance_days"])

        self._report(counts)

    # --- Organización --------------------------------------------------------- #

    def _company(self) -> Company:
        return department_services.create_company(
            actor=None,
            request=None,
            code=DEMO_COMPANY,
            legal_name="Ceiba Consultores, S.A.",
            tax_id="1234567-8",
            country="GT",
        )

    def _areas(self, company: Company) -> dict:
        direction = department_services.create_department(
            actor=None, request=None, company=company, code="DIR", name="Dirección General"
        )
        areas = {"DIR": direction}
        for code, name in AREAS.items():
            areas[code] = department_services.create_department(
                actor=None, request=None, company=company, code=code, name=name, parent=direction
            )
        return areas

    def _positions(self, areas: dict) -> dict:
        grades: dict[str, Any] = {}
        positions = {}
        for key, (area, title, grade_code, minimum, maximum, _head, _role) in POSITIONS.items():
            if grade_code not in grades:
                grades[grade_code] = position_services.create_job_grade(
                    actor=None,
                    request=None,
                    code=grade_code,
                    name=f"Grado {grade_code}",
                    level=int(grade_code[1:]),
                    min_salary=Decimal(minimum),
                    max_salary=Decimal(maximum),
                )
            positions[key] = position_services.create_position(
                actor=None,
                request=None,
                department=areas[area],
                job_grade=grades[grade_code],
                code=f"{area}-{key}",
                title=title,
            )
        return positions

    def _schedule(self):
        return attendance_services.create_schedule(
            actor=None,
            request=None,
            code="OFI",
            name="Oficina 8 a 17",
            weekly_hours=40,
            grace_minutes=10,
            days=[
                {
                    "weekday": weekday,
                    "start_time": dt.time(8, 0),
                    "end_time": dt.time(17, 0),
                    "break_minutes": 60,
                }
                for weekday in (
                    Weekday.MONDAY,
                    Weekday.TUESDAY,
                    Weekday.WEDNESDAY,
                    Weekday.THURSDAY,
                    Weekday.FRIDAY,
                )
            ],
        )

    def _holidays(self, company: Company) -> None:
        year = timezone.localdate().year
        for month, day, name in ((5, 1, "Día del Trabajo"), (9, 15, "Independencia")):
            Holiday.objects.get_or_create(
                company=company, date=dt.date(year, month, day), defaults={"name": name}
            )

    # --- Personas -------------------------------------------------------------- #

    def _employees(self, company: Company, positions: dict, schedule, people: int) -> list:
        today = timezone.localdate()
        employees = []

        for index, data in enumerate(PEOPLE[:people], start=1):
            account = self._account(data)
            hire_date = today - dt.timedelta(days=365 * (1 + index % 6) + index * 7)
            employee = create_employee(
                actor=None,
                request=None,
                person_data={
                    "first_name": data["first"],
                    "last_name": data["last"],
                    "second_last_name": data["second"],
                    "birth_date": today - dt.timedelta(days=365 * (24 + index)),
                },
                employee_code=f"CEI-{index:03d}",
                hire_date=hire_date,
                user=account,
            )

            contract = contract_services.create_contract(
                employee=employee,
                actor=None,
                request=None,
                company=company,
                contract_type="INDEFINITE",
                start_date=hire_date,
            )
            contract_services.set_salary(
                contract=contract,
                amount=Decimal(data["salary"]),
                effective_from=hire_date,
                change_reason="INITIAL",
                actor=None,
                request=None,
            )
            contract_services.add_assignment(
                contract=contract,
                position=positions[data["role"]],
                start_date=hire_date,
                actor=None,
                request=None,
            )
            contract_services.activate_contract(contract=contract, actor=None, request=None)
            attendance_services.assign_schedule(
                contract=contract,
                work_schedule=schedule,
                start_date=hire_date,
                actor=None,
                request=None,
            )
            employees.append(employee)

        return employees

    def _account(self, data: dict):
        """Cuenta de demostración **sin contraseña utilizable**.

        No se inventa ninguna contraseña: quien quiera entrar con esta cuenta la
        fija con `changepassword`, y así nadie hereda una clave conocida.
        """
        user_model = get_user_model()
        first = data["first"].split()[0].lower().translate(ACCENTS)
        last = data["last"].lower().translate(ACCENTS)
        account = user_model.objects.create_user(email=f"{first}.{last}@ceiba.test")
        account.set_unusable_password()
        account.save(update_fields=["password"])

        role = POSITIONS[data["role"]][6]
        account.groups.set(Group.objects.filter(name=role))
        return account

    def _headships(self, areas: dict, employees: list) -> None:
        for data, employee in zip(PEOPLE, employees, strict=False):
            area, _title, _grade, _min, _max, is_head, _role = POSITIONS[data["role"]]
            if not is_head:
                continue
            department_services.assign_head(
                department=areas[area],
                employee=employee,
                start_date=employee.hire_date,
                actor=None,
                request=None,
                appointment_note="Datos de demostración",
            )

    # --- Movimiento ------------------------------------------------------------- #

    def _attendance(self, employees: list, days: int) -> int:
        today = timezone.localdate()
        punched = 0
        for offset in range(days, 0, -1):
            day = today - dt.timedelta(days=offset)
            if day.weekday() > 4:  # fin de semana
                continue
            for index, employee in enumerate(employees):
                # La jornada es de 08:00 a 17:00 con una hora de almuerzo: ocho
                # horas. Salir a las 16:00 es un día normal; lo demás abre
                # incidencia, y sin algo de variedad no se ve funcionar nada.
                late = 25 if (index + offset) % 7 == 0 else 0
                extra = 90 if (index + offset) % 11 == 0 else 0
                attendance_services.check_in(
                    employee=employee, actor=None, request=None, at=_aware(day, 8, late)
                )
                attendance_services.check_out(
                    employee=employee, actor=None, request=None, at=_aware(day, 16, late + extra)
                )
                punched += 1
        return punched

    def _leave(self, employees: list) -> None:
        vacation = leave_services.create_leave_type(
            actor=None,
            request=None,
            code="VAC",
            name="Vacaciones",
            default_annual_days=Decimal("15"),
            min_notice_days=3,
        )
        sick = leave_services.create_leave_type(
            actor=None,
            request=None,
            code="ENF",
            name="Incapacidad",
            default_annual_days=Decimal("0"),
            allows_negative_balance=True,
            is_sensitive=True,
            max_backdating_days=15,
        )

        today = timezone.localdate()
        month = today.replace(day=1)
        for employee in employees:
            for offset in range(6):  # medio año de devengo
                leave_services.accrue_month(
                    employee=employee, leave_type=vacation, month_start=_months_back(month, offset)
                )

        hr_user = employees[0].user  # la jefatura de RRHH aprueba
        monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 + 7)

        # Con una organización recortada puede no haber tanta gente: se piden
        # las ausencias que quepan, no se rompe.
        if len(employees) > 3:
            approved = self._request(employees[3], vacation, monday, 5)
            leave_services.approve_request(
                leave_request=approved, actor=hr_user, request=None, note="Programado con el área"
            )
        if len(employees) > 7:
            self._request(employees[7], vacation, monday + dt.timedelta(days=14), 3)
        if len(employees) > 5:
            self._request(
                employees[5], sick, today - dt.timedelta(days=3), 2, reason="Reportado después"
            )

    def _request(self, employee, leave_type, start, days: int, reason: str = ""):
        request = leave_services.create_request(
            employee=employee,
            leave_type=leave_type,
            start_date=start,
            end_date=start + dt.timedelta(days=days - 1),
            reason=reason,
            actor=employee.user,
            request=None,
        )
        return leave_services.submit_request(
            leave_request=request, actor=employee.user, request=None
        )

    def _documents(self, employees: list) -> None:
        contract_type = document_services.create_document_type(
            actor=None,
            request=None,
            code="CON",
            name="Contrato firmado",
            allowed_extensions="pdf",
            max_size_mb=5,
            retention_years=5,
        )
        medical = document_services.create_document_type(
            actor=None,
            request=None,
            code="MED",
            name="Constancia médica",
            allowed_extensions="pdf",
            max_size_mb=5,
            is_sensitive=True,
            requires_expiry=True,
        )

        today = timezone.localdate()
        for index, employee in enumerate(employees[:6]):
            document_services.upload_document(
                employee=employee,
                document_type=contract_type,
                upload=SimpleUploadedFile(
                    f"contrato-{employee.employee_code}.pdf",
                    DEMO_PDF + str(index).encode(),  # checksum distinto por persona
                    content_type="application/pdf",
                ),
                title=f"Contrato {employee.person.full_name}",
                issued_on=employee.hire_date,
                expires_on=None,
                actor=None,
                request=None,
            )
            if index % 3 == 0:
                document_services.upload_document(
                    employee=employee,
                    document_type=medical,
                    upload=SimpleUploadedFile(
                        f"constancia-{employee.employee_code}.pdf",
                        DEMO_PDF + f"med{index}".encode(),
                        content_type="application/pdf",
                    ),
                    title="Constancia médica anual",
                    issued_on=today - dt.timedelta(days=300),
                    expires_on=today + dt.timedelta(days=20),  # una por vencer
                    actor=None,
                    request=None,
                )

    # --- Resumen ---------------------------------------------------------------- #

    def _report(self, counts: dict[str, int]) -> None:
        self.stdout.write(self.style.SUCCESS("Datos de demostración listos:"))
        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count}")
        # Se imprime el intérprete que está corriendo este comando, no un
        # `python` genérico: copiado tal cual funciona aunque el entorno
        # virtual no esté activado en la terminal.
        self.stdout.write(
            "\nLas cuentas de demostración no tienen contraseña utilizable. Para entrar\n"
            "con una de ellas, fíjela usted:\n"
            f'  "{sys.executable}" manage.py changepassword ana.lopez@ceiba.test'
        )


def _aware(day: dt.date, hour: int, extra_minutes: int) -> dt.datetime:
    moment = dt.datetime.combine(day, dt.time(hour, 0)) + dt.timedelta(minutes=extra_minutes)
    return timezone.make_aware(moment, timezone.get_current_timezone())


def _months_back(month_start: dt.date, offset: int) -> dt.date:
    month, year = month_start.month - offset, month_start.year
    while month <= 0:
        month += 12
        year -= 1
    return dt.date(year, month, 1)
