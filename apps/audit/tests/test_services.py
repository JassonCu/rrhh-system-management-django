"""Servicio de auditoría: depuración de datos sensibles y captura de contexto."""

from __future__ import annotations

import uuid

import pytest
from django.test import RequestFactory

from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.services import record, sanitize_metadata
from apps.core.logging import REDACTED


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    ["password", "PASSWORD", "new_password", "api_key", "authorization", "csrf_token", "dpi"],
)
def test_sensitive_keys_are_redacted(key: str) -> None:
    assert sanitize_metadata({key: "valor-secreto"})[key] == REDACTED


@pytest.mark.unit
def test_redaction_is_recursive() -> None:
    cleaned = sanitize_metadata(
        {
            "changes": {"email": "a@b.com", "password": "hunter2"},
            "items": [{"token": "abc"}, {"name": "ok"}],
        }
    )
    assert cleaned["changes"]["password"] == REDACTED
    assert cleaned["changes"]["email"] == "a@b.com"
    assert cleaned["items"][0]["token"] == REDACTED
    assert cleaned["items"][1]["name"] == "ok"


@pytest.mark.unit
def test_redaction_stops_on_deep_structures() -> None:
    """Una estructura patológica no debe agotar la pila."""
    payload: dict = {}
    node = payload
    for _ in range(30):
        node["child"] = {}
        node = node["child"]
    assert sanitize_metadata(payload) is not None


@pytest.mark.django_db
@pytest.mark.security
def test_record_never_persists_a_secret(user) -> None:
    event = record(
        action=AuditAction.PASSWORD_CHANGE,
        actor=user,
        metadata={"password": "hunter2", "field": "email"},
    )
    event.refresh_from_db()
    assert event.metadata["password"] == REDACTED
    assert "hunter2" not in str(event.metadata)
    assert event.metadata["field"] == "email"


@pytest.mark.django_db
def test_record_snapshots_the_actor(user) -> None:
    event = record(action=AuditAction.LOGIN, actor=user)
    assert event.actor == user
    assert event.actor_repr == str(user)


@pytest.mark.django_db
def test_record_without_actor_is_attributed_to_the_system() -> None:
    event = record(action=AuditAction.USER_CREATE)
    assert event.actor is None
    assert event.actor_repr == "system"


@pytest.mark.django_db
def test_record_captures_request_context(user) -> None:
    request = RequestFactory().post("/accounts/login/", HTTP_USER_AGENT="pytest-agent")
    request.user = user
    request.request_id = uuid.uuid4()

    event = record(action=AuditAction.LOGIN, request=request)

    assert event.actor == user  # se toma del request cuando no se pasa explícito
    assert event.ip_address == "127.0.0.1"
    assert event.user_agent == "pytest-agent"
    assert event.request_id == request.request_id


@pytest.mark.django_db
def test_forwarded_for_is_ignored_without_a_trusted_proxy(settings, user) -> None:
    """Sin proxy declarado, la IP registrada no puede falsificarse por cabecera."""
    settings.TRUST_PROXY_HEADERS = False
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.9")
    request.user = user

    event = record(action=AuditAction.LOGIN, request=request)

    assert event.ip_address == "127.0.0.1"


@pytest.mark.django_db
def test_forwarded_for_is_used_behind_a_trusted_proxy(settings, user) -> None:
    settings.TRUST_PROXY_HEADERS = True
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1")
    request.user = user

    event = record(action=AuditAction.LOGIN, request=request)

    assert event.ip_address == "203.0.113.9"


@pytest.mark.django_db
def test_record_describes_the_object(company) -> None:
    event = record(action=AuditAction.EMPLOYEE_UPDATE, obj=company, outcome=AuditOutcome.SUCCESS)
    assert event.object_type == "core.Company"
    assert event.object_id == str(company.pk)
    assert event.object_repr == company.legal_name
