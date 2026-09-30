"""Generación y exportación de reportes.

Dos invariantes de esta capa:

- **RN-70**: un reporte solo se arma con los selectores de su app de origen, que
  ya aplican el alcance de quien consulta. La exportación no amplía lo que la
  pantalla muestra: es el mismo cálculo, otro formato.
- **RN-71**: **toda** exportación se audita. Sacar datos del sistema es la
  operación que más conviene poder reconstruir después.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.core.exceptions import ConflictError
from apps.reports.builders import BUILDERS, Filters, ReportResult
from apps.reports.constants import REPORTS, ReportSpec

#: Formatos que se pueden exportar. El valor viaja en la URL y en la
#: bitácora: es ASCII estable y no se traduce.
EXPORT_FORMATS = ("xlsx", "pdf")

#: Tipo MIME de un libro de Excel moderno.
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Tipo MIME de un PDF.
PDF_CONTENT_TYPE = "application/pdf"


def spec_for(slug: str) -> ReportSpec:
    spec = REPORTS.get(slug)
    if spec is None:
        raise ConflictError("unknown_report", slug=slug)
    return spec


def build(*, slug: str, user, filters: Filters) -> ReportResult:
    """Calcula el reporte. El alcance lo ponen los selectores de cada app."""
    spec_for(slug)
    return BUILDERS[slug](user, filters)


def export_to_excel(*, slug: str, result: ReportResult, filters: Filters) -> bytes:
    """Arma el libro de Excel. Solo formato: ninguna decisión de negocio aquí."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    spec = spec_for(slug)
    workbook = Workbook()
    sheet = workbook.active
    # El nombre de hoja de Excel admite 31 caracteres y ni `[]:*?/\`.
    sheet.title = _sheet_title(str(spec.title))

    sheet.append([str(spec.title)])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append([filters.describe()])
    moment = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    sheet.append([_("Generated on %(moment)s") % {"moment": moment}])
    sheet.append([])

    # `append([])` no crea celdas, así que `max_row` no avanza: el índice se
    # toma **después** de escribir el encabezado, o se estilaría la fila
    # equivocada y el panel se congelaría donde no toca.
    sheet.append([str(column.label) for column in result.columns])
    header_row = sheet.max_row
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for row in result.rows:
        sheet.append([_as_cell(row.get(column.key)) for column in result.columns])

    if result.truncated:
        # El archivo viaja solo: si se recortó, tiene que decirlo dentro.
        sheet.append([])
        sheet.append([_("The report was cut: only the first rows are included.")])
        sheet[sheet.max_row][0].font = Font(bold=True, color="B3261E")

    if result.totals:
        sheet.append([])
        totals_row = [_as_cell(result.totals.get(column.key, "")) for column in result.columns]
        if totals_row and not totals_row[0]:
            totals_row[0] = _("Total")
        sheet.append(totals_row)
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)

    for index, column in enumerate(result.columns, start=1):
        width = max(len(str(column.label)) + 2, 14)
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def export_to_pdf(
    *,
    slug: str,
    result: ReportResult,
    filters: Filters,
    generated_by: str,
    report_url: str,
) -> tuple[bytes, bool]:
    """Arma el PDF con su QR y su marca de agua de trazabilidad."""
    from apps.reports.pdf import build_pdf

    spec = spec_for(slug)
    return build_pdf(
        title=str(spec.title),
        result=result,
        filters_text=filters.describe(),
        generated_by=generated_by,
        generated_at=timezone.localtime().strftime("%Y-%m-%d %H:%M"),
        report_url=report_url,
    )


def _sheet_title(title: str) -> str:
    """Nombre de hoja admisible: 31 caracteres y sin los que Excel prohíbe."""
    for forbidden in "[]:*?/\\":
        title = title.replace(forbidden, "-")
    return title[:31]


def record_export(
    *,
    slug: str,
    user,
    filters: Filters,
    result: ReportResult,
    fmt: str,
    request: HttpRequest | None,
    extra: dict | None = None,
) -> None:
    """Deja constancia de la exportación (RN-71).

    Se guarda **qué** se sacó y con qué filtros, nunca el contenido: la bitácora
    no es una copia de los datos.
    """
    record(
        action=AuditAction.EXPORT_DATA,
        actor=user,
        request=request,
        metadata={
            "report": slug,
            "format": fmt,
            "rows": result.row_count,
            "truncated": result.truncated,
            "date_from": filters.date_from.isoformat(),
            "date_to": filters.date_to.isoformat(),
            "department": filters.department.code if filters.department else None,
            **(extra or {}),
        },
    )


def filename_for(slug: str, filters: Filters, extension: str) -> str:
    """Nombre de archivo estable y sin datos personales."""
    return f"{slug}-{filters.date_from:%Y%m%d}-{filters.date_to:%Y%m%d}.{extension}"


#: Caracteres con los que Excel empieza a interpretar una celda como fórmula.
#: Un texto que empiece así se neutraliza antes de escribirlo
#: (docs/security/revision-reportes.md, H-1).
FORMULA_STARTERS = ("=", "+", "-", "@", "\t", "\r")


def _as_cell(value):
    """Excel entiende fechas y números; lo demás va como texto **inerte**.

    Un título como `=HYPERLINK("http://...")` se ejecutaría al abrir el libro y
    podría sacar de la hoja los datos de al lado. Los importes y las fechas
    siguen yendo tipados, para que las sumas de la hoja funcionen.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, int | float | Decimal):
        # Decimal llega tal cual: Excel debe recibir un número, no un texto que
        # parezca número, o las sumas de la hoja no funcionan.
        return value
    if hasattr(value, "isoformat"):
        return value
    return _neutralise(str(value))


def _neutralise(text: str) -> str:
    """Antepone un apóstrofo al texto que Excel tomaría por fórmula.

    El apóstrofo no se ve en la celda: solo le dice a Excel que lo trate como
    texto. Es la defensa estándar contra la inyección de fórmulas, y va aquí
    —en el punto de escritura— para que ningún reporte futuro la olvide.
    """
    return f"'{text}" if text.startswith(FORMULA_STARTERS) else text
