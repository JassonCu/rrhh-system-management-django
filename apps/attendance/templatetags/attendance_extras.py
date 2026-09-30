"""Filtros de presentación de asistencia.

Solo formato: ninguna decisión de negocio ni de seguridad vive aquí (regla 3).
"""

from __future__ import annotations

from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def as_hours(minutes: int | None) -> str:
    """480 → «8 h», 252 → «4 h 12 min», 0 → «—»."""
    if not minutes:
        return "—"
    hours, remainder = divmod(int(minutes), 60)
    if hours and remainder:
        return _("%(hours)s h %(minutes)s min") % {"hours": hours, "minutes": remainder}
    if hours:
        return _("%(hours)s h") % {"hours": hours}
    return _("%(minutes)s min") % {"minutes": remainder}
