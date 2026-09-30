"""Filtro de redacción: ningún secreto puede llegar a un archivo de log (RN-72)."""

from __future__ import annotations

import logging

import pytest

from apps.core.logging import REDACTED, RequestIDFilter, SensitiveDataFilter, redact, request_id_var


def _record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, args, None)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "password=hunter2",
        "password: hunter2",
        "'password': 'hunter2'",
        '"password": "hunter2"',
        "token=hunter2",
        "api_key=hunter2",
        "Authorization: hunter2",
        "sessionid=hunter2",
        "dpi=hunter2",
        "activation_code=hunter2",
    ],
)
def test_secret_values_are_removed(text: str) -> None:
    result = redact(text)
    assert "hunter2" not in result
    assert REDACTED in result


@pytest.mark.unit
def test_redaction_is_case_insensitive() -> None:
    assert "hunter2" not in redact("PASSWORD=hunter2")


@pytest.mark.unit
def test_harmless_text_is_left_intact() -> None:
    text = "employee_code=EMP-0042 department=IT"
    assert redact(text) == text


@pytest.mark.unit
def test_filter_redacts_interpolated_arguments() -> None:
    """El dato puede llegar en args, no solo en el mensaje."""
    record = _record("login attempt password=%s", "hunter2")
    SensitiveDataFilter().filter(record)
    assert "hunter2" not in record.getMessage()


@pytest.mark.unit
def test_filter_always_lets_the_record_through() -> None:
    record = _record("plain message")
    assert SensitiveDataFilter().filter(record) is True


@pytest.mark.unit
def test_request_id_filter_adds_the_identifier() -> None:
    token = request_id_var.set("abc-123")
    try:
        record = _record("something happened")
        RequestIDFilter().filter(record)
        assert record.request_id == "abc-123"
    finally:
        request_id_var.reset(token)


@pytest.mark.unit
def test_request_id_defaults_outside_a_request() -> None:
    record = _record("background job")
    RequestIDFilter().filter(record)
    assert record.request_id == "-"
