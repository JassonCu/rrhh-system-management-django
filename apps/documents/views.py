"""Vistas del expediente documental.

Tres capas en cada vista: autenticación, permiso y alcance. La descarga añade
una cuarta —confidencialidad del tipo— y una quinta —la bitácora— **antes** de
entregar un solo byte (§K.4).

Nunca se publica un enlace a `/media/`: esta vista es el único camino al archivo.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import ConflictError
from apps.documents import selectors, services
from apps.documents.forms import ArchiveDocumentForm, DocumentTypeForm, DocumentUploadForm
from apps.documents.validators import safe_display_name
from apps.employees.selectors import get_employee_or_404

ERROR_MESSAGES = {
    "empty_file": _("That file is empty."),
    "file_too_large": _("That file exceeds the size allowed for this document type."),
    "extension_not_allowed": _("That format is not accepted for this document type."),
    "content_does_not_match_extension": _(
        "The file claims to be of that format but its content is not."
    ),
    "content_type_mismatch": _("The file type reported by your browser does not match."),
    "type_without_formats": _("That document type does not accept any format yet."),
    "duplicate_document": _("That same file is already in this file."),
    "document_type_inactive": _("That document type is no longer available."),
    "expiry_required": _("This document type requires an expiry date."),
    "dates_unordered": _("The expiry cannot precede the issue date."),
    "archiving_needs_reason": _("Archiving a document requires a reason."),
    "document_already_archived": _("That document is already archived."),
}


def _message_for(error: ConflictError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


def _file_tab_url(employee) -> str:
    return f"{reverse('employees:detail', args=[employee.public_id])}?tab=file"


@login_required
@permission_required("documents.add_employeedocument", raise_exception=True)
@require_http_methods(["GET", "POST"])
def document_upload(request: HttpRequest, employee_public_id) -> HttpResponse:
    """Sube un documento a una ficha. La ficha sale de la URL, no del POST."""
    employee = get_employee_or_404(request.user, public_id=employee_public_id)
    form = DocumentUploadForm(
        request.POST or None, request.FILES or None, user=request.user, employee=employee
    )

    if request.method == "POST" and form.is_valid():
        try:
            services.upload_document(
                employee=employee,
                document_type=form.cleaned_data["document_type"],
                upload=form.cleaned_data["file"],
                title=form.cleaned_data["title"],
                issued_on=form.cleaned_data["issued_on"],
                expires_on=form.cleaned_data["expires_on"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Document uploaded."))
            return redirect(_file_tab_url(employee))

    return render(
        request,
        "documents/upload.html",
        {
            "form": form,
            "employee": employee,
            "types": selectors.uploadable_types_for(request.user, employee),
            "cancel_url": _file_tab_url(employee),
        },
    )


@login_required
@permission_required("documents.view_employeedocument", raise_exception=True)
def document_download(request: HttpRequest, public_id) -> HttpResponse:
    """Entrega el archivo. Autoriza, audita y **después** lo sirve (RN-63)."""
    document = selectors.get_document_or_404(request.user, public_id=public_id)
    if not selectors.can_open(request.user, document):
        # 403 y no 404: que el documento existe ya se ve en la ficha; lo que no
        # se puede es abrirlo (§J.2, patrón UX §4.2).
        raise PermissionDenied

    path = Path(document.stored_path.path).resolve()
    media_root = Path(settings.MEDIA_ROOT).resolve()
    if not path.is_relative_to(media_root) or not path.is_file():
        # La ruta la genera el sistema, pero se verifica igual: si algún día
        # alguien la escribe a mano, no debe salir de MEDIA_ROOT (§K.4).
        raise Http404

    services.record_download(document=document, actor=request.user, request=request)

    response = FileResponse(
        path.open("rb"),
        as_attachment=True,  # nunca `inline`: un SVG o HTML no debe ejecutarse
        filename=safe_display_name(document.original_filename),
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@permission_required("documents.archive_document", raise_exception=True)
@require_http_methods(["GET", "POST"])
def document_archive(request: HttpRequest, public_id) -> HttpResponse:
    # La única vista que alcanza a los archivados: necesita poder decir que ya
    # lo estaban.
    document = selectors.get_document_or_404(
        request.user, public_id=public_id, include_archived=True
    )
    form = ArchiveDocumentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            services.archive_document(
                document=document,
                reason=form.cleaned_data["reason"],
                actor=request.user,
                request=request,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Document archived."))
            return redirect(_file_tab_url(document.employee))

    return render(
        request,
        "documents/archive.html",
        {
            "form": form,
            "document": document,
            "cancel_url": _file_tab_url(document.employee),
        },
    )


@login_required
@permission_required("documents.view_employeedocument", raise_exception=True)
def expiring_documents(request: HttpRequest) -> HttpResponse:
    """Lo que vence pronto, al alcance de quien consulta."""
    page = Paginator(selectors.expiring_soon(request.user), 25).get_page(request.GET.get("page"))
    return render(request, "documents/expiring.html", {"page": page})


@login_required
@permission_required("documents.view_documenttype", raise_exception=True)
def type_list(request: HttpRequest) -> HttpResponse:
    types = selectors.types_visible_for(request.user).order_by("-is_active", "name")
    return render(request, "documents/type_list.html", {"types": types})


@login_required
@permission_required("documents.add_documenttype", raise_exception=True)
@require_http_methods(["GET", "POST"])
def type_create(request: HttpRequest) -> HttpResponse:
    form = DocumentTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_document_type(actor=request.user, request=request, **form.cleaned_data)
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Document type created."))
            return redirect("documents:type_list")
    return render(request, "documents/type_form.html", {"form": form})


@login_required
@permission_required("documents.change_documenttype", raise_exception=True)
@require_http_methods(["GET", "POST"])
def type_update(request: HttpRequest, pk: int) -> HttpResponse:
    document_type = get_object_or_404(selectors.types_visible_for(request.user), pk=pk)
    form = DocumentTypeForm(request.POST or None, instance=document_type)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_document_type(
                document_type=document_type,
                actor=request.user,
                request=request,
                **form.cleaned_data,
            )
        except ConflictError as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(request, _("Document type updated."))
            return redirect("documents:type_list")
    return render(
        request, "documents/type_form.html", {"form": form, "document_type": document_type}
    )
