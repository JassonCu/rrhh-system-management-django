"""El comando de datos de demostración."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditEvent
from apps.contracts.models import EmploymentContract
from apps.employees.models import Employee

#: Organización recortada: la suite no necesita las doce personas.
SMALL = 4

pytestmark = pytest.mark.django_db


@pytest.fixture
def development(settings, tmp_path):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings


def test_it_creates_a_working_organisation(development) -> None:
    """Los datos pasan por los servicios: los contratos quedan **activos**."""
    call_command("seed_demo", attendance_days=0, people=SMALL, verbosity=0)

    demo = Employee.objects.filter(employee_code__startswith="CEI-")
    assert demo.count() == SMALL
    assert EmploymentContract.objects.filter(status="ACTIVE").count() == SMALL
    assert AuditEvent.objects.exists()  # pasar por los servicios deja rastro


def test_running_it_twice_changes_nothing(development) -> None:
    call_command("seed_demo", attendance_days=0, people=SMALL, verbosity=0)
    before = (Employee.objects.count(), EmploymentContract.objects.count())

    call_command("seed_demo", attendance_days=0, people=SMALL, verbosity=0)

    assert (Employee.objects.count(), EmploymentContract.objects.count()) == before


def test_the_demo_accounts_have_no_usable_password(development) -> None:
    """Nadie hereda una contraseña conocida: se fija con `changepassword`."""
    call_command("seed_demo", attendance_days=0, people=SMALL, verbosity=0)

    accounts = [
        employee.user
        for employee in Employee.objects.filter(employee_code__startswith="CEI-")
        if employee.user
    ]

    assert accounts
    assert all(not account.has_usable_password() for account in accounts)


def test_it_generates_attendance_with_incidents(development) -> None:
    call_command("seed_demo", attendance_days=6, people=SMALL, verbosity=0)

    employee = Employee.objects.filter(employee_code__startswith="CEI-").first()

    assert employee.attendance_entries.exists()


@pytest.mark.security
def test_it_refuses_to_run_outside_development(settings) -> None:
    """Inventa personas y contratos: en producción sería contaminar los datos."""
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_demo", verbosity=0)

    assert not Employee.objects.filter(employee_code__startswith="CEI-").exists()
