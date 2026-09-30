"""Vistas de reportes.

Tres capas como siempre: autenticación, permiso —el del reporte, declarado en
`constants.REPORTS`— y alcance, que ponen los selectores de cada app dentro del
constructor.

La exportación **no** es una vista aparte con sus propias reglas: es la misma
vista con otro formato, así que pasa por los mismos filtros y el mismo permiso.
Lo único que añade es el registro en la bitácora (RN-71).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from apps.reports import services
from apps.reports.constants import REPORTS, SCREEN_ROW_LIMIT
from apps.reports.forms import ReportFilterForm


def _visible_reports(user) -> list:
    """Los reportes que este usuario puede pedir, por permiso."""
    return [spec for spec in REPORTS.values() if user.has_perm(spec.permission)]


@login_required
def report_index(request: HttpRequest) -> HttpResponse:
    """Portada: solo los reportes que quien mira puede abrir."""
    return render(request, "reports/index.html", {"reports": _visible_reports(request.user)})


@login_required
def report_detail(request: HttpRequest, slug: str) -> HttpResponse:
    spec = REPORTS.get(slug)
    if spec is None:
        raise Http404
    if not request.user.has_perm(spec.permission):
        # 403 y no 404: el reporte existe y está en la portada de quien sí puede.
        raise PermissionDenied

    form = ReportFilterForm(request.GET or None, user=request.user)
    result = None
    if request.GET and form.is_valid():
        filters = form.as_filters()
        result = services.build(slug=slug, user=request.user, filters=filters)

        fmt = request.GET.get("format", "")
        if fmt in services.EXPORT_FORMATS:
            return _export(request, slug=slug, filters=filters, result=result, fmt=fmt)

    return render(
        request,
        "reports/detail.html",
        {
            "spec": spec,
            "form": form,
            "result": result,
            "visible_rows": result.rows[:SCREEN_ROW_LIMIT] if result else [],
            "screen_limit": SCREEN_ROW_LIMIT,
            "export_query": _export_query(request),
            "pdf_query": _export_query(request, fmt="pdf"),
        },
    )


def _export(request: HttpRequest, *, slug, filters, result, fmt) -> HttpResponse:
    """Entrega el archivo. **Primero la bitácora**, después los bytes (RN-71)."""
    if fmt == "pdf":
        # El QR del PDF apunta a esta misma pantalla, con los mismos filtros:
        # abrirlo desde el celular exige iniciar sesión, como cualquier otra vista.
        report_url = request.build_absolute_uri(f"{request.path}?{_filters_query(request)}")
        content, truncated = services.export_to_pdf(
            slug=slug,
            result=result,
            filters=filters,
            generated_by=_actor_label(request.user),
            report_url=report_url,
        )
        content_type = services.PDF_CONTENT_TYPE
        extra = {"watermark": _actor_label(request.user), "pdf_truncated": truncated}
    else:
        content = services.export_to_excel(slug=slug, result=result, filters=filters)
        content_type = services.XLSX_CONTENT_TYPE
        extra = None

    services.record_export(
        slug=slug,
        user=request.user,
        filters=filters,
        result=result,
        fmt=fmt,
        request=request,
        extra=extra,
    )

    response = HttpResponse(content, content_type=content_type)
    filename = services.filename_for(slug, filters, fmt)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _actor_label(user) -> str:
    """Quién aparece en la marca de agua: nombre si lo hay, si no el correo."""
    employee = getattr(user, "employee", None)
    if employee is not None:
        return f"{employee.person.full_name} ({employee.employee_code})"
    return user.get_username()


def _filters_query(request: HttpRequest) -> str:
    """Los filtros de la pantalla, **sin** el formato: el QR abre la vista."""
    params = request.GET.copy()
    params.pop("format", None)
    return params.urlencode()


def _export_query(request: HttpRequest, fmt: str = "xlsx") -> str:
    """Los mismos filtros de la pantalla, más el formato.

    Se reconstruye desde `request.GET` para que exportar sea exactamente lo que
    se está viendo, no una consulta distinta escrita a mano.
    """
    params = request.GET.copy()
    params["format"] = fmt
    return params.urlencode()
