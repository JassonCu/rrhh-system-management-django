"""Seguridad de las plantillas: autoescape intacto y CSP respetada.

Dos puntos del checklist §K.9 que estaban documentados pero sin verificación
automática. Una regla que solo vive en un documento se incumple en el mes tres.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]

#: Solo nuestras plantillas. Las de terceros se revisan al elegir la dependencia,
#: no en cada ejecución de la suite.
TEMPLATE_ROOTS = (BASE_DIR / "templates", BASE_DIR / "apps")


def iter_templates() -> list[Path]:
    found: list[Path] = []
    for root in TEMPLATE_ROOTS:
        if root.exists():
            found += [p for p in root.rglob("*.html") if ".venv" not in p.parts]
    return sorted(found)


TEMPLATES = iter_templates()

#: Desactivan el autoescape de Django, que es la primera barrera contra XSS.
UNSAFE_FILTERS = re.compile(r"\|\s*safe\b|mark_safe|\{%\s*autoescape\s+off")

#: `<script>` con contenido propio. Los externos (`<script src=...>`) sí valen:
#: la CSP los permite desde el propio origen.
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", re.IGNORECASE)

#: Bloques `<style>` y atributos `style=`: los prohíbe `style-src` sin
#: `unsafe-inline` (ADR-007).
INLINE_STYLE_BLOCK = re.compile(r"<style[^>]*>", re.IGNORECASE)
INLINE_STYLE_ATTR = re.compile(r"\sstyle\s*=\s*[\"']", re.IGNORECASE)

#: Manejadores en línea: `onclick`, `onsubmit`, etc. Los bloquea la CSP.
INLINE_HANDLER = re.compile(r"\son[a-z]+\s*=\s*[\"']", re.IGNORECASE)

#: `{# ... #}` de varias líneas. Django solo admite ese comentario en UNA línea:
#: si abarca más, **se muestra en la página**. Se detectó al probar a mano: la
#: barra de navegación enseñaba notas internas sobre permisos.
MULTILINE_COMMENT = re.compile(r"\{#(?:(?!#\}).)*?\n.*?#\}", re.DOTALL)


def relative(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


@pytest.mark.security
def test_there_are_templates_to_inspect() -> None:
    """Si el descubrimiento fallara, el resto pasaría en vacío."""
    assert len(TEMPLATES) >= 10


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_no_template_disables_autoescaping(template: Path) -> None:
    """`|safe` sobre datos de usuario es la vía directa al XSS almacenado."""
    matches = UNSAFE_FILTERS.findall(template.read_text(encoding="utf-8"))
    assert not matches, (
        f"{relative(template)} desactiva el autoescape ({matches}). "
        "Si es imprescindible, justifícalo en la revisión del PR."
    )


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_no_template_has_inline_scripts(template: Path) -> None:
    """La CSP sin `unsafe-inline` los bloquearía: fallarían en silencio."""
    content = template.read_text(encoding="utf-8")
    assert not INLINE_SCRIPT.search(content), (
        f"{relative(template)} lleva un <script> con código embebido. "
        "Muévelo a static/js/ (ADR-007)."
    )


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_no_template_has_inline_styles(template: Path) -> None:
    content = template.read_text(encoding="utf-8")
    assert not INLINE_STYLE_BLOCK.search(content), (
        f"{relative(template)} lleva un bloque <style>. Muévelo a static/css/."
    )
    assert not INLINE_STYLE_ATTR.search(content), (
        f'{relative(template)} lleva un atributo style="". Usa una clase CSS.'
    )


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_no_template_has_inline_event_handlers(template: Path) -> None:
    """`onclick=` y compañía: los bloquea la CSP y además mezclan capas."""
    content = template.read_text(encoding="utf-8")
    matches = INLINE_HANDLER.findall(content)
    assert not matches, (
        f"{relative(template)} usa manejadores en línea ({matches}). "
        "Engánchalos con addEventListener desde static/js/."
    )


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_state_changing_forms_carry_a_csrf_token(template: Path) -> None:
    """Todo formulario POST necesita su token; sin él, Django devolvería 403."""
    content = template.read_text(encoding="utf-8")
    post_forms = re.findall(r"<form[^>]*method\s*=\s*[\"']post[\"'][^>]*>", content, re.IGNORECASE)
    if not post_forms:
        pytest.skip("la plantilla no envía formularios por POST")
    assert "{% csrf_token %}" in content, (
        f"{relative(template)} tiene un formulario POST sin {{% csrf_token %}}."
    )


@pytest.mark.security
@pytest.mark.parametrize("template", TEMPLATES, ids=relative)
def test_no_template_has_multiline_short_comments(template: Path) -> None:
    """Un comentario que se ve en pantalla filtra notas internas al usuario."""
    content = template.read_text(encoding="utf-8")
    match = MULTILINE_COMMENT.search(content)
    assert match is None, (
        f"{relative(template)} tiene un {{# #}} de varias líneas; use "
        "{% comment %}...{% endcomment %}."
    )


@pytest.mark.security
def test_the_detector_actually_detects(tmp_path: Path) -> None:
    """Comprueba los patrones contra muestras conocidas, para no pasar en vacío."""
    assert UNSAFE_FILTERS.search("{{ valor|safe }}")
    assert UNSAFE_FILTERS.search("{% autoescape off %}")
    assert INLINE_SCRIPT.search("<script>alert(1)</script>")
    assert not INLINE_SCRIPT.search('<script src="/static/js/main.js" defer></script>')
    assert INLINE_STYLE_ATTR.search('<div style="color:red">')
    assert INLINE_HANDLER.search('<button onclick="go()">')
    assert not INLINE_HANDLER.search('<button data-action="go">')
    assert MULTILINE_COMMENT.search("{# primera línea\n segunda #}")
    assert not MULTILINE_COMMENT.search("{# una sola línea #}\n<p>texto</p>\n{# otra #}")
