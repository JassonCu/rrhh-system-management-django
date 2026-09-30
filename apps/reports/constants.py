"""Catálogo de reportes.

Cada reporte se declara **una sola vez** aquí: su nombre, el permiso que exige y
qué filtros usa. Las vistas, el menú y la exportación leen de esta declaración,
así que añadir un reporte es añadir una entrada y su constructor, no tocar
cinco archivos.

Los **valores** (los `slug`) son ASCII estable: viajan en la URL y en la
bitácora, y no se traducen (§O.3.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

#: Máximo de filas que se muestran en pantalla. Más que eso se exporta.
SCREEN_ROW_LIMIT = 500

#: Máximo de filas que admite una exportación. Es un límite de memoria y, sobre
#: todo, una señal: si alguien necesita más, hay que hablar de otra cosa.
EXPORT_ROW_LIMIT = 20_000

#: Rango máximo de fechas que puede pedir un reporte, en días (inclusive).
MAX_RANGE_DAYS = 400

#: Máximo de filas que caben razonablemente en un PDF. Más que eso es un Excel.
PDF_ROW_LIMIT = 2_000


@dataclass(frozen=True)
class ReportSpec:
    """Lo que el sistema sabe de un reporte antes de calcularlo."""

    slug: str
    title: str
    description: str
    #: Permiso necesario. El **alcance** lo pone el selector de cada app: este
    #: permiso solo abre la puerta, no decide a quién se ve.
    permission: str


REPORTS: dict[str, ReportSpec] = {
    "attendance": ReportSpec(
        slug="attendance",
        title=_("Attendance by period"),
        description=_("Worked and expected hours, late arrivals and absences per person."),
        permission="attendance.view_attendanceentry",
    ),
    "leave": ReportSpec(
        slug="leave",
        title=_("Leave and balances"),
        description=_("Requests in the period and the balance of each leave type."),
        permission="leave.view_leaverequest",
    ),
    "headcount": ReportSpec(
        slug="headcount",
        title=_("Headcount and contracts"),
        description=_("Active people, their contract and what expires in the period."),
        permission="employees.view_employee",
    ),
    "documents": ReportSpec(
        slug="documents",
        title=_("Files and expiries"),
        description=_("Documents on file and those expiring in the period."),
        permission="documents.view_employeedocument",
    ),
}
