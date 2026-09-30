"""Constantes transversales.

Las funciones de esta unidad se usan como ``choices``/``default`` invocables
(Django 5.0+). Frente a ``choices=settings.LANGUAGES``, el invocable guarda en la
migración una referencia a la función y no la lista literal: cambiar los idiomas
soportados no genera una migración espuria, y la única fuente de verdad sigue
siendo ``settings``.
"""

from django.conf import settings

COUNTRY_CODE_LENGTH = 2
CURRENCY_CODE_LENGTH = 3


def language_choices() -> list[tuple[str, str]]:
    return list(settings.LANGUAGES)


def default_language() -> str:
    return settings.LANGUAGE_CODE
