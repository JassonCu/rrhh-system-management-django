"""Restricciones e integridad de personas y empleados."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone, translation

from apps.employees.constants import ContactType, DocumentType, EmploymentStatus
from apps.employees.models import (
    Address,
    ContactMethod,
    EmergencyContact,
    Employee,
    IdentityDocument,
    Person,
)
from apps.employees.tests.conftest import valid_cui

pytestmark = pytest.mark.django_db


# --- Person ---------------------------------------------------------------- #


def test_full_name_is_derived_not_stored(make_person) -> None:
    """Almacenarlo violaría BCNF y dejaría el valor obsoleto al corregir un apellido."""
    person = make_person(
        first_name="Ana", middle_name="María", last_name="Pérez", second_last_name="López"
    )
    assert person.full_name == "Ana María Pérez López"

    field_names = {f.name for f in Person._meta.get_fields()}
    assert "full_name" not in field_names


def test_full_name_follows_a_rename(make_person) -> None:
    person = make_person(first_name="Ana", last_name="Pérez")
    person.last_name = "Ramírez"
    assert "Ramírez" in person.full_name


def test_future_birth_date_is_rejected(make_person) -> None:
    person = Person(
        first_name="X", last_name="Y", birth_date=timezone.localdate() + dt.timedelta(days=1)
    )
    with pytest.raises(ValidationError):
        person.full_clean()


def test_implausible_birth_year_is_rejected_by_the_database() -> None:
    """El límite inferior sí cabe en un CHECK; `CURRENT_DATE` no es inmutable."""
    with pytest.raises(IntegrityError):
        Person.objects.create(first_name="X", last_name="Y", birth_date=dt.date(1080, 1, 1))


def test_age_at_handles_the_birthday_boundary(make_person) -> None:
    person = make_person(birth_date=dt.date(2000, 6, 15))
    assert person.age_at(dt.date(2018, 6, 14)) == 17
    assert person.age_at(dt.date(2018, 6, 15)) == 18


def test_str_is_not_translated(make_person) -> None:
    person = make_person(first_name="Ana", last_name="Pérez")
    with translation.override("en"):
        english = str(person)
    with translation.override("es-gt"):
        spanish = str(person)
    assert english == spanish


# --- IdentityDocument ------------------------------------------------------ #


def test_document_number_is_normalized_on_save(person) -> None:
    cui = valid_cui()
    document = IdentityDocument.objects.create(
        person=person, document_type=DocumentType.DPI, number=f"{cui[:4]}-{cui[4:]}"
    )
    assert document.number == cui


def test_the_same_document_cannot_be_registered_twice(person, make_person) -> None:
    """Dos personas no pueden compartir un DPI: es la unicidad natural (RN-02)."""
    cui = valid_cui()
    IdentityDocument.objects.create(person=person, document_type=DocumentType.DPI, number=cui)

    with pytest.raises(IntegrityError):
        IdentityDocument.objects.create(
            person=make_person(), document_type=DocumentType.DPI, number=cui
        )


def test_only_one_permanent_document_per_type(person) -> None:
    """RN-03, en su forma expresable como índice parcial."""
    IdentityDocument.objects.create(
        person=person, document_type=DocumentType.DPI, number=valid_cui(19283746)
    )
    with pytest.raises(IntegrityError):
        IdentityDocument.objects.create(
            person=person, document_type=DocumentType.DPI, number=valid_cui(55555555)
        )


def test_a_document_with_expiry_does_not_collide(person) -> None:
    """La restricción es sobre los permanentes: un pasaporte renovado es legítimo."""
    IdentityDocument.objects.create(
        person=person,
        document_type=DocumentType.PASSPORT,
        number="X1111111",
        expires_on=dt.date(2030, 1, 1),
    )
    IdentityDocument.objects.create(
        person=person,
        document_type=DocumentType.PASSPORT,
        number="X2222222",
        expires_on=dt.date(2035, 1, 1),
    )
    assert person.identity_documents.count() == 2


def test_expiry_cannot_precede_issue(person) -> None:
    with pytest.raises(IntegrityError):
        IdentityDocument.objects.create(
            person=person,
            document_type=DocumentType.PASSPORT,
            number="X1",
            issued_on=dt.date(2030, 1, 1),
            expires_on=dt.date(2020, 1, 1),
        )


def test_invalid_cui_is_rejected_by_clean(person) -> None:
    """El CUI inválido se construye alterando el verificador de uno válido.

    Elegir un literal "que parezca inválido" es frágil: 1234567890123 resulta
    tener el verificador correcto y la prueba pasaba por el motivo equivocado.
    """
    cui = valid_cui()
    broken = f"{cui[:8]}{(int(cui[8]) + 1) % 10}{cui[9:]}"

    document = IdentityDocument(person=person, document_type=DocumentType.DPI, number=broken)
    with pytest.raises(ValidationError):
        document.full_clean()


@pytest.mark.security
def test_str_masks_the_number(person) -> None:
    """`__str__` alimenta `AuditEvent.object_repr`: un DPI no puede acabar ahí."""
    cui = valid_cui()
    document = IdentityDocument.objects.create(
        person=person, document_type=DocumentType.DPI, number=cui
    )
    assert cui not in str(document)
    assert cui[-4:] in str(document)


def test_documents_follow_the_person(person) -> None:
    """CASCADE dentro del agregado; la persona está protegida por `Employee`."""
    IdentityDocument.objects.create(
        person=person, document_type=DocumentType.DPI, number=valid_cui()
    )
    person.delete()
    assert IdentityDocument.objects.count() == 0


# --- ContactMethod --------------------------------------------------------- #


def test_email_is_normalized_to_lowercase(person) -> None:
    contact = ContactMethod.objects.create(
        person=person, contact_type=ContactType.PERSONAL_EMAIL, value=" Ana@Example.COM "
    )
    assert contact.value == "ana@example.com"


def test_phone_spaces_are_stripped(person) -> None:
    contact = ContactMethod.objects.create(
        person=person, contact_type=ContactType.MOBILE, value="5555 1234"
    )
    assert contact.value == "55551234"


def test_only_one_primary_contact_per_type(person) -> None:
    ContactMethod.objects.create(
        person=person, contact_type=ContactType.MOBILE, value="55551234", is_primary=True
    )
    with pytest.raises(IntegrityError):
        ContactMethod.objects.create(
            person=person, contact_type=ContactType.MOBILE, value="55555678", is_primary=True
        )


def test_a_primary_of_each_type_is_allowed(person) -> None:
    ContactMethod.objects.create(
        person=person, contact_type=ContactType.MOBILE, value="55551234", is_primary=True
    )
    ContactMethod.objects.create(
        person=person, contact_type=ContactType.PERSONAL_EMAIL, value="a@b.com", is_primary=True
    )
    assert person.contact_methods.filter(is_primary=True).count() == 2


def test_the_same_value_cannot_repeat_for_a_person(person) -> None:
    ContactMethod.objects.create(person=person, contact_type=ContactType.MOBILE, value="55551234")
    with pytest.raises(IntegrityError):
        ContactMethod.objects.create(
            person=person, contact_type=ContactType.MOBILE, value="55551234"
        )


# --- Address --------------------------------------------------------------- #


def test_only_one_primary_address(person) -> None:
    Address.objects.create(
        person=person, line1="Calle 1", locality="Guatemala", region="Guatemala", is_primary=True
    )
    with pytest.raises(IntegrityError):
        Address.objects.create(
            person=person, line1="Calle 2", locality="Mixco", region="Guatemala", is_primary=True
        )


# --- Employee -------------------------------------------------------------- #


def test_employee_code_is_unique(make_employee) -> None:
    make_employee(employee_code="EMP-9999")
    with pytest.raises(IntegrityError):
        make_employee(employee_code="EMP-9999")


def test_person_is_protected(employee_record) -> None:
    """Un empleado sin persona no tiene sentido: la persona no se borra."""
    with pytest.raises(ProtectedError):
        employee_record.person.delete()


def test_deleting_the_account_keeps_the_employee(make_employee, user) -> None:
    """`SET_NULL`, nunca `CASCADE`: retirar el acceso no borra al empleado."""
    employee = make_employee(user=user)
    user.delete()

    employee.refresh_from_db()
    assert employee.user is None
    assert Employee.objects.filter(pk=employee.pk).exists()


def test_termination_date_cannot_precede_hire(make_employee) -> None:
    employee = make_employee()
    employee.employment_status = EmploymentStatus.TERMINATED
    employee.termination_date = employee.hire_date - dt.timedelta(days=1)
    with pytest.raises(IntegrityError):
        employee.save()


def test_terminated_status_requires_a_date(make_employee) -> None:
    employee = make_employee()
    employee.employment_status = EmploymentStatus.TERMINATED
    with pytest.raises(IntegrityError):
        employee.save()


def test_a_date_requires_the_terminated_status(make_employee) -> None:
    """La incoherencia inversa también se rechaza: uno sin el otro es un dato falso."""
    employee = make_employee()
    employee.termination_date = dt.date(2025, 1, 1)
    with pytest.raises(IntegrityError):
        employee.save()


def test_public_id_is_generated_and_unique(make_employee) -> None:
    first, second = make_employee(), make_employee()
    assert first.public_id != second.public_id


def test_employee_has_no_organizational_fields() -> None:
    """Departamento, puesto y salario son hechos con vigencia: viven en contracts."""
    field_names = {f.name for f in Employee._meta.get_fields()}
    assert not {"department", "position", "salary", "manager"} & field_names


# --- EmergencyContact ------------------------------------------------------ #


def test_priority_is_unique_per_employee(employee_record) -> None:
    EmergencyContact.objects.create(
        employee=employee_record,
        full_name="Luis Pérez",
        relationship="PARENT",
        phone="55550000",
        priority=1,
    )
    with pytest.raises(IntegrityError):
        EmergencyContact.objects.create(
            employee=employee_record,
            full_name="Marta Pérez",
            relationship="SIBLING",
            phone="55551111",
            priority=1,
        )


def test_priority_must_be_positive(employee_record) -> None:
    with pytest.raises(IntegrityError):
        EmergencyContact.objects.create(
            employee=employee_record,
            full_name="X",
            relationship="OTHER",
            phone="1",
            priority=0,
        )


@pytest.mark.unit
def test_expiry_uses_guatemala_date_not_server_date(person, monkeypatch) -> None:
    """Regresión: con `date.today()` el servidor decide qué día es.

    A las 03:00 UTC del 1 de enero todavía es 31 de diciembre en Guatemala
    (UTC-6). Un documento que vence el 31 de diciembre NO está vencido para
    RRHH, aunque un servidor en UTC ya haya cambiado de día.
    """
    utc_moment = dt.datetime(2026, 1, 1, 3, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(timezone, "now", lambda: utc_moment)

    document = IdentityDocument.objects.create(
        person=person,
        document_type=DocumentType.PASSPORT,
        number="X9999999",
        expires_on=dt.date(2025, 12, 31),
    )

    assert timezone.localdate() == dt.date(2025, 12, 31)
    assert document.is_expired is False
