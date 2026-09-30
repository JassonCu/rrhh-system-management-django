"""Alcance, IDOR y enmascarado de PII.

Es la suite más importante de la Fase 3: verifica que la URL **no determina el
permiso** y que ver una ficha no implica ver los datos sensibles de esa ficha
(§J.4, regla 32).
"""

from __future__ import annotations

import uuid

import pytest
from django.http import Http404
from django.urls import reverse

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.departments.models import Department, DepartmentHeadship
from apps.employees import selectors
from apps.employees.constants import DocumentType
from apps.employees.models import IdentityDocument
from apps.employees.tests.conftest import valid_cui

pytestmark = pytest.mark.django_db


@pytest.fixture
def own_employee(make_user, make_employee):
    """Un usuario con rol EMPLOYEE y su ficha vinculada."""
    account = make_user("propio@example.com", Role.EMPLOYEE)
    return account, make_employee(user=account)


@pytest.fixture
def other_employee(make_employee):
    """La ficha de otra persona: el objetivo de cualquier intento de IDOR."""
    return make_employee()


# --- Alcance del selector -------------------------------------------------- #


@pytest.mark.security
def test_hr_sees_the_whole_organization(make_user, other_employee) -> None:
    hr = make_user("hr.scope@example.com", Role.HR_ADMIN)
    assert other_employee in selectors.employees_visible_for(hr)


@pytest.mark.security
def test_auditor_sees_the_whole_organization(make_user, other_employee) -> None:
    auditor = make_user("aud.scope@example.com", Role.AUDITOR)
    assert other_employee in selectors.employees_visible_for(auditor)


@pytest.mark.security
def test_employee_sees_only_their_own_record(own_employee, other_employee) -> None:
    account, own = own_employee
    visible = selectors.employees_visible_for(account)

    assert list(visible) == [own]
    assert other_employee not in visible


@pytest.mark.security
def test_anonymous_sees_nothing(django_user_model, other_employee) -> None:
    from django.contrib.auth.models import AnonymousUser

    assert list(selectors.employees_visible_for(AnonymousUser())) == []


@pytest.mark.security
def test_an_account_without_an_employee_record_sees_nothing(make_user, other_employee) -> None:
    """Una cuenta sin ficha no es nadie en el dominio, por mucho rol que tenga."""
    orphan = make_user("huerfano@example.com", Role.EMPLOYEE)
    assert list(selectors.employees_visible_for(orphan)) == []


@pytest.mark.security
def test_headship_query_works_today(make_user, make_employee, company) -> None:
    """La mitad que sí se puede construir ya: qué departamentos jefea alguien."""
    from apps.departments.selectors import departments_headed_by

    account = make_user("jefe2@example.com", Role.MANAGER)
    record = make_employee(user=account)
    root = Department.objects.create(company=company, code="DIR", name="Dirección")
    child = Department.objects.create(company=company, code="TI", name="TI", parent=root)
    DepartmentHeadship.objects.create(department=root, employee=record, start_date="2024-01-01")

    headed = departments_headed_by(account)

    assert {root.pk, child.pk} == headed, "jefear incluye el subárbol"


@pytest.mark.security
def test_an_ended_headship_grants_nothing(make_user, make_employee, company) -> None:
    from apps.departments.selectors import departments_headed_by

    account = make_user("exjefe@example.com", Role.MANAGER)
    record = make_employee(user=account)
    department = Department.objects.create(company=company, code="TI", name="TI")
    DepartmentHeadship.objects.create(
        department=department, employee=record, start_date="2020-01-01", end_date="2023-12-31"
    )

    assert departments_headed_by(account) == set()


# --- IDOR ------------------------------------------------------------------ #


@pytest.mark.security
def test_out_of_scope_record_raises_404_not_403(own_employee, other_employee) -> None:
    """Un 403 confirmaría que el empleado existe."""
    account, _own = own_employee
    with pytest.raises(Http404):
        selectors.get_employee_or_404(account, public_id=other_employee.public_id)


@pytest.mark.security
def test_changing_the_uuid_in_the_url_grants_nothing(client, own_employee, other_employee) -> None:
    """El UUID dificulta la enumeración, pero **no es** el control de acceso."""
    account, own = own_employee
    client.force_login(account)

    assert client.get(reverse("employees:detail", args=[own.public_id])).status_code == 200
    assert (
        client.get(reverse("employees:detail", args=[other_employee.public_id])).status_code == 404
    )


@pytest.mark.security
def test_a_random_uuid_is_404(client, own_employee) -> None:
    account, _own = own_employee
    client.force_login(account)
    response = client.get(reverse("employees:detail", args=[uuid.uuid4()]))
    assert response.status_code == 404


@pytest.mark.security
def test_editing_someone_else_is_refused(client, make_user, other_employee) -> None:
    """Tener el permiso de edición no basta: hace falta que el objeto esté en alcance."""
    account = make_user("editor@example.com", Role.EMPLOYEE)
    client.force_login(account)

    response = client.post(
        reverse("employees:update", args=[other_employee.public_id]),
        {
            "person-first_name": "Intruso",
            "person-last_name": "X",
            "person-birth_date": "1990-01-01",
        },
    )

    assert response.status_code in {403, 404}
    other_employee.person.refresh_from_db()
    assert other_employee.person.first_name != "Intruso"


@pytest.mark.security
def test_documents_are_scoped_too(own_employee, other_employee) -> None:
    """Los datos anidados aplican su propio alcance, no el del padre."""
    account, _own = own_employee
    IdentityDocument.objects.create(
        person=other_employee.person, document_type=DocumentType.DPI, number=valid_cui()
    )

    assert list(selectors.identity_documents_for(account, other_employee)) == []


# --- Enmascarado de PII ---------------------------------------------------- #


@pytest.mark.security
def test_hr_can_see_sensitive_pii(make_user, other_employee) -> None:
    hr = make_user("hr.pii@example.com", Role.HR_ADMIN)
    assert selectors.can_view_sensitive_pii(hr, other_employee) is True


@pytest.mark.security
def test_the_person_can_see_their_own_sensitive_pii(own_employee) -> None:
    account, own = own_employee
    assert selectors.can_view_sensitive_pii(account, own) is True


@pytest.mark.security
def test_a_manager_cannot_see_sensitive_pii(make_user, other_employee) -> None:
    """Sin cascada: ver la ficha no da acceso al DPI ni a la fecha de nacimiento."""
    manager = make_user("jefe.pii@example.com", Role.MANAGER)
    assert selectors.can_view_sensitive_pii(manager, other_employee) is False


@pytest.mark.security
def test_the_detail_page_masks_the_document_for_a_manager(
    client, make_user, other_employee, manager_with_team
) -> None:
    """Comprobación de extremo a extremo sobre el HTML entregado."""
    cui = valid_cui()
    IdentityDocument.objects.create(
        person=other_employee.person, document_type=DocumentType.DPI, number=cui
    )
    # Los documentos viven en su pestaña desde la UX-2.
    documents_tab = {"tab": "documents"}
    hr = make_user("hr.render@example.com", Role.HR_ADMIN)
    client.force_login(hr)
    full = client.get(reverse("employees:detail", args=[other_employee.public_id]), documents_tab)
    assert cui.encode() in full.content

    client.force_login(manager_with_team)
    masked = client.get(reverse("employees:detail", args=[other_employee.public_id]), documents_tab)

    assert masked.status_code == 200
    assert cui.encode() not in masked.content, "el DPI completo llegó al HTML"
    assert cui[-4:].encode() in masked.content


@pytest.mark.security
def test_the_list_never_shows_documents(client, make_user, other_employee) -> None:
    cui = valid_cui()
    IdentityDocument.objects.create(
        person=other_employee.person, document_type=DocumentType.DPI, number=cui
    )
    hr = make_user("hr.list@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    response = client.get(reverse("employees:list"))

    assert response.status_code == 200
    assert cui.encode() not in response.content


# --- Auditoría del acceso sensible ----------------------------------------- #


@pytest.mark.security
def test_viewing_sensitive_data_is_audited(client, make_user, other_employee) -> None:
    """No basta con controlar quién puede verlos: hay que saber quién los vio."""
    hr = make_user("hr.audit@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    client.get(reverse("employees:detail", args=[other_employee.public_id]))

    event = AuditEvent.objects.filter(action=AuditAction.EMPLOYEE_VIEW_SENSITIVE).latest(
        "occurred_at"
    )
    assert event.actor == hr
    assert event.object_id == str(other_employee.public_id)


@pytest.mark.security
def test_a_masked_view_is_not_recorded_as_sensitive_access(
    client, other_employee, manager_with_team
) -> None:
    """Si se registrara igual, el rastro dejaría de significar nada."""
    client.force_login(manager_with_team)

    response = client.get(reverse("employees:detail", args=[other_employee.public_id]))

    assert response.status_code == 200, "la prueba solo vale si el jefe llega a ver la ficha"
    assert not AuditEvent.objects.filter(action=AuditAction.EMPLOYEE_VIEW_SENSITIVE).exists()


@pytest.mark.security
def test_hr_manager_does_see_sensitive_pii(make_user, other_employee) -> None:
    """Deja escrito lo que la versión anterior de estas pruebas asumió mal.

    Según la matriz §J.2, `HR_MANAGER` sí ve PII sensible. Usarlo como perfil
    "sin acceso" hacía fallar las pruebas por un error de la prueba, no del código.
    """
    hr_manager = make_user("hrm.pii@example.com", Role.HR_MANAGER)
    assert selectors.can_view_sensitive_pii(hr_manager, other_employee) is True


# --- Revisión de seguridad de la Fase 3: contactos personales -------------- #


def _add_contacts(employee) -> None:
    from apps.employees.constants import ContactType
    from apps.employees.models import ContactMethod, EmergencyContact

    person = employee.person
    ContactMethod.objects.create(
        person=person, contact_type=ContactType.PERSONAL_EMAIL, value="privado@correo.com"
    )
    ContactMethod.objects.create(person=person, contact_type=ContactType.MOBILE, value="55009999")
    ContactMethod.objects.create(
        person=person, contact_type=ContactType.WORK_EMAIL, value="laboral@empresa.com"
    )
    EmergencyContact.objects.create(
        employee=employee,
        full_name="Contacto Confidencial",
        relationship="PARENT",
        phone="55001111",
    )


@pytest.mark.security
def test_manager_sees_only_the_work_contact(client, other_employee, manager_with_team) -> None:
    """Hallazgo de la revisión: un jefe veía teléfonos y correos personales."""
    _add_contacts(other_employee)
    client.force_login(manager_with_team)

    response = client.get(reverse("employees:detail", args=[other_employee.public_id]))

    assert response.status_code == 200
    assert b"laboral@empresa.com" in response.content
    assert b"privado@correo.com" not in response.content
    assert b"55009999" not in response.content


@pytest.mark.security
def test_manager_does_not_see_emergency_contacts(client, other_employee, manager_with_team) -> None:
    """Son PII de terceros que ni siquiera trabajan en la organización."""
    _add_contacts(other_employee)
    client.force_login(manager_with_team)

    response = client.get(reverse("employees:detail", args=[other_employee.public_id]))

    assert b"Contacto Confidencial" not in response.content
    assert b"55001111" not in response.content


@pytest.mark.security
def test_hr_sees_all_personal_contacts(client, make_user, other_employee) -> None:
    _add_contacts(other_employee)
    client.force_login(make_user("hr.contacts@example.com", Role.HR_ADMIN))

    response = client.get(reverse("employees:detail", args=[other_employee.public_id]))

    assert b"privado@correo.com" in response.content
    assert b"Contacto Confidencial" in response.content


@pytest.mark.security
def test_personal_contact_selectors_are_scoped(own_employee, other_employee) -> None:
    """Fuera de alcance no sale nada, ni siquiera el correo laboral."""
    account, _own = own_employee
    _add_contacts(other_employee)

    assert list(selectors.contact_methods_for(account, other_employee)) == []
    assert list(selectors.emergency_contacts_for(account, other_employee)) == []


@pytest.mark.security
def test_viewing_your_own_record_is_not_logged_as_sensitive_access(client, own_employee) -> None:
    """Hallazgo de la revisión: el autoacceso llenaba la bitácora de ruido."""
    account, own = own_employee
    client.force_login(account)

    response = client.get(reverse("employees:detail", args=[own.public_id]))

    assert response.status_code == 200
    assert not AuditEvent.objects.filter(action=AuditAction.EMPLOYEE_VIEW_SENSITIVE).exists()


# --- Alcance de equipo (Fase 4): contratos y asignaciones reales ------------ #


def _hire_into(employee, company, department, *, code: str):
    """Contrata a alguien en un puesto del departamento usando los servicios reales."""
    import datetime as dt
    from decimal import Decimal

    from apps.contracts import services as contract_services
    from apps.positions.models import JobGrade, Position

    grade, _created = JobGrade.objects.get_or_create(
        code="GQ", defaults={"name": "Equipo", "level": 3, "min_salary": 5000, "max_salary": 9000}
    )
    position = Position.objects.create(
        department=department, job_grade=grade, code=code, title=f"Analista {code}"
    )
    start = dt.date(2024, 1, 1)
    contract = contract_services.create_contract(
        employee=employee,
        actor=None,
        request=None,
        company=company,
        contract_type="INDEFINITE",
        start_date=start,
    )
    contract_services.set_salary(
        contract=contract,
        amount=Decimal("6000"),
        effective_from=start,
        change_reason="INITIAL",
        actor=None,
        request=None,
    )
    contract_services.add_assignment(
        contract=contract, position=position, start_date=start, actor=None, request=None
    )
    contract_services.activate_contract(contract=contract, actor=None, request=None)
    return contract


@pytest.fixture
def manager_with_team(make_user, make_employee, company, other_employee):
    """Un MANAGER con un subordinado real: jefatura, contrato vivo y asignación vigente.

    En la Fase 3 este vínculo se simulaba; desde la Fase 4 toda la cadena es el
    código de producción.
    """
    account = make_user("jefe.equipo@example.com", Role.MANAGER)
    record = make_employee(user=account)
    department = Department.objects.create(company=company, code="EQ", name="Equipo")
    DepartmentHeadship.objects.create(
        department=department, employee=record, start_date="2024-01-01"
    )
    _hire_into(other_employee, company, department, code="EQ-1")
    return account


@pytest.mark.security
def test_manager_sees_the_team_through_current_assignments(
    manager_with_team, other_employee, make_employee
) -> None:
    """Sustituye a la prueba que documentaba el hueco de la Fase 3."""
    visible = selectors.employees_visible_for(manager_with_team)

    assert other_employee in visible
    assert make_employee() not in visible, "sin asignación en su departamento no es su equipo"


@pytest.mark.security
def test_someone_in_another_department_is_not_on_the_team(
    manager_with_team, make_employee, company
) -> None:
    elsewhere = Department.objects.create(company=company, code="OT", name="Otra área")
    outsider = make_employee()
    _hire_into(outsider, company, elsewhere, code="OT-1")

    assert outsider not in selectors.employees_visible_for(manager_with_team)


@pytest.mark.security
def test_terminating_the_contract_removes_the_person_from_the_team(
    manager_with_team, other_employee
) -> None:
    """La salida del alcance es inmediata, en la misma transacción que la baja."""
    import datetime as dt

    from apps.contracts import services as contract_services

    contract_services.terminate_contract(
        contract=other_employee.contracts.get(),
        termination_date=dt.date(2025, 1, 31),
        reason="RESIGNATION",
        actor=None,
        request=None,
    )

    assert other_employee not in selectors.employees_visible_for(manager_with_team)


@pytest.mark.security
def test_a_manager_still_cannot_see_the_team_contracts(manager_with_team, other_employee) -> None:
    """Ver la ficha del equipo no da acceso a sus contratos (§J.2, sin cascada)."""
    from apps.contracts import selectors as contract_selectors

    visible = contract_selectors.contracts_visible_for(manager_with_team)
    assert not visible.filter(employee=other_employee).exists()
