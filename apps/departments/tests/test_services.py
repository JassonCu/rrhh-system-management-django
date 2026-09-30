"""Invariantes del organigrama que la base no puede expresar (§E.4)."""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError
from apps.core.models import Company
from apps.departments import selectors, services
from apps.departments.models import Department
from apps.positions.models import JobGrade, Position

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_with_user(hr_admin):
    request = RequestFactory().post("/departamentos/")
    request.user = hr_admin
    return request


@pytest.fixture
def tree(company: Company):
    """Organigrama de tres niveles: DIR → TI → DEV."""
    root = Department.objects.create(company=company, code="DIR", name="Dirección")
    it = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    dev = Department.objects.create(company=company, code="DEV", name="Desarrollo", parent=it)
    return root, it, dev


# --- Aciclicidad (RN-31) --------------------------------------------------- #


def test_direct_cycle_is_rejected(request_with_user, hr_admin, tree) -> None:
    root, it, _dev = tree
    with pytest.raises(ConflictError) as error:
        services.update_department(
            department=root, actor=hr_admin, request=request_with_user, parent=it
        )
    assert error.value.code == "department_cycle"


def test_indirect_cycle_is_rejected(request_with_user, hr_admin, tree) -> None:
    """El caso que un constraint simple no atrapa: DIR → ... → DEV → DIR."""
    root, _it, dev = tree
    with pytest.raises(ConflictError) as error:
        services.update_department(
            department=root, actor=hr_admin, request=request_with_user, parent=dev
        )
    assert error.value.code == "department_cycle"


def test_self_parent_is_rejected(request_with_user, hr_admin, tree) -> None:
    _root, it, _dev = tree
    with pytest.raises(ConflictError):
        services.update_department(
            department=it, actor=hr_admin, request=request_with_user, parent=it
        )


def test_reparenting_within_the_tree_is_allowed(request_with_user, hr_admin, tree) -> None:
    """Mover una rama hacia arriba es legítimo y no debe bloquearse."""
    root, _it, dev = tree
    services.update_department(
        department=dev, actor=hr_admin, request=request_with_user, parent=root
    )
    dev.refresh_from_db()
    assert dev.parent == root


def test_parent_must_belong_to_the_same_company(request_with_user, hr_admin, tree) -> None:
    root, _it, _dev = tree
    other_company = Company.objects.create(code="F", legal_name="Filial", tax_id="9-9")
    foreign = Department.objects.create(company=other_company, code="X", name="Ajeno")

    with pytest.raises(ConflictError) as error:
        services.update_department(
            department=root, actor=hr_admin, request=request_with_user, parent=foreign
        )
    assert error.value.code == "department_parent_in_another_company"


# --- Subárbol -------------------------------------------------------------- #


def test_descendant_ids_covers_the_whole_subtree(tree) -> None:
    """Es la base del alcance de un MANAGER: jefear incluye las dependencias."""
    root, it, dev = tree
    assert selectors.descendant_ids([root.pk]) == {root.pk, it.pk, dev.pk}
    assert selectors.descendant_ids([it.pk]) == {it.pk, dev.pk}
    assert selectors.descendant_ids([dev.pk]) == {dev.pk}


def test_descendant_ids_terminates_with_a_cycle(tree) -> None:
    root, it, _dev = tree
    Department.objects.filter(pk=root.pk).update(parent=it)
    assert len(selectors.descendant_ids([root.pk])) <= 3


# --- Desactivación (RN-33) ------------------------------------------------- #


def test_cannot_deactivate_with_active_children(request_with_user, hr_admin, tree) -> None:
    root, _it, _dev = tree
    with pytest.raises(ConflictError) as error:
        services.deactivate_department(department=root, actor=hr_admin, request=request_with_user)
    assert error.value.code == "department_has_active_children"


def test_cannot_deactivate_with_active_positions(request_with_user, hr_admin, tree) -> None:
    _root, _it, dev = tree
    grade = JobGrade.objects.create(
        code="G1", name="Base", level=1, min_salary=3000, max_salary=5000
    )
    Position.objects.create(department=dev, job_grade=grade, code="P1", title="Analista")

    with pytest.raises(ConflictError) as error:
        services.deactivate_department(department=dev, actor=hr_admin, request=request_with_user)
    assert error.value.code == "department_has_active_positions"


def test_deactivation_is_a_state_change_not_a_delete(request_with_user, hr_admin, tree) -> None:
    _root, _it, dev = tree
    services.deactivate_department(department=dev, actor=hr_admin, request=request_with_user)

    dev.refresh_from_db()
    assert dev.is_active is False
    assert Department.objects.filter(pk=dev.pk).exists()


# --- Auditoría ------------------------------------------------------------- #


def test_creation_is_audited(request_with_user, hr_admin, company) -> None:
    department = services.create_department(
        actor=hr_admin, request=request_with_user, company=company, code="RH", name="Recursos"
    )
    event = AuditEvent.objects.get(action=AuditAction.DEPARTMENT_CREATE)
    assert event.actor == hr_admin
    assert event.object_id == str(department.pk)


def test_update_records_the_previous_values(request_with_user, hr_admin, tree) -> None:
    _root, it, _dev = tree
    services.update_department(
        department=it, actor=hr_admin, request=request_with_user, name="Sistemas"
    )
    event = AuditEvent.objects.get(action=AuditAction.DEPARTMENT_UPDATE)
    assert event.metadata["from"]["name"] == "Tecnología"


def test_deactivation_is_audited(request_with_user, hr_admin, tree) -> None:
    _root, _it, dev = tree
    services.deactivate_department(department=dev, actor=hr_admin, request=request_with_user)
    assert AuditEvent.objects.filter(action=AuditAction.DEPARTMENT_DEACTIVATE).exists()
