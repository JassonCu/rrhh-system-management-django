"""La bitácora es append-only. Estas pruebas son la garantía de RN-70."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.models import AuditEvent, AuditLogImmutableError

pytestmark = pytest.mark.django_db


@pytest.fixture
def event() -> AuditEvent:
    return AuditEvent.objects.create(
        actor_repr="system",
        action=AuditAction.LOGIN,
        outcome=AuditOutcome.SUCCESS,
    )


@pytest.mark.security
def test_existing_event_cannot_be_modified(event: AuditEvent) -> None:
    event.action = AuditAction.LOGOUT
    with pytest.raises(AuditLogImmutableError):
        event.save()

    event.refresh_from_db()
    assert event.action == AuditAction.LOGIN


@pytest.mark.security
def test_event_cannot_be_deleted(event: AuditEvent) -> None:
    with pytest.raises(AuditLogImmutableError):
        event.delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.security
def test_queryset_update_is_blocked(event: AuditEvent) -> None:
    """Sin esto, un `.update()` masivo saltaría por encima de `Model.save`."""
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.filter(pk=event.pk).update(outcome=AuditOutcome.FAILURE)


@pytest.mark.security
def test_queryset_delete_is_blocked(event: AuditEvent) -> None:
    # Se compara contra lo que había: la sincronización de roles deja sus
    # propios eventos `PERMISSION_CHANGE` al preparar la base de pruebas.
    before = AuditEvent.objects.count()

    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.all().delete()

    assert AuditEvent.objects.count() == before
    assert AuditEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.security
def test_change_and_delete_permissions_do_not_exist() -> None:
    """No basta con no otorgarlos: directamente no se generan (§J.3)."""
    content_type = ContentType.objects.get_for_model(AuditEvent)
    codenames = set(
        Permission.objects.filter(content_type=content_type).values_list("codename", flat=True)
    )
    assert "change_auditevent" not in codenames
    assert "delete_auditevent" not in codenames
    assert {"add_auditevent", "view_auditevent", "view_audit_log"} <= codenames


@pytest.mark.unit
def test_event_survives_actor_deletion(user) -> None:
    """El rastro no puede desaparecer al borrar la cuenta que lo generó."""
    event = AuditEvent.objects.create(
        actor=user,
        actor_repr=str(user),
        action=AuditAction.LOGIN,
    )
    user.delete()

    event.refresh_from_db()
    assert event.actor is None
    assert event.actor_repr == "empleado@example.com"


@pytest.mark.unit
def test_str_is_not_translated(event: AuditEvent) -> None:
    from django.utils import translation

    with translation.override("en"):
        english = str(event)
    with translation.override("es-gt"):
        spanish = str(event)
    assert english == spanish
