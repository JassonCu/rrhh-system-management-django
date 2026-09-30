"""Consultas de lectura del expediente documental (ADR-005).

El alcance se apoya en `employees_visible_for`, como el resto del sistema, y
encima añade la regla propia de la fase: **el contenido de un documento
confidencial solo lo abre quien tiene `view_sensitive_document`**. Que el
documento *exista* sí se ve: RRHH necesita poder pedirlo (§J.2, patrón UX §4.2).
"""

from __future__ import annotations

import datetime as dt

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.documents.constants import EXPIRY_WARNING_DAYS
from apps.documents.models import DocumentType, EmployeeDocument
from apps.employees.selectors import employees_visible_for


def types_visible_for(user) -> QuerySet[DocumentType]:
    if not user.is_authenticated or not user.has_perm("documents.view_documenttype"):
        return DocumentType.objects.none()
    return DocumentType.objects.all()


def documents_visible_for(user, *, include_archived: bool = False) -> QuerySet[EmployeeDocument]:
    """Documentos de las fichas al alcance de quien consulta."""
    if not user.is_authenticated:
        return EmployeeDocument.objects.none()
    documents = EmployeeDocument.objects.filter(
        employee__in=employees_visible_for(user)
    ).select_related("employee__person", "document_type")
    return documents if include_archived else documents.filter(is_active=True)


def get_document_or_404(user, *, public_id, include_archived: bool = False) -> EmployeeDocument:
    """Documento dentro del alcance; fuera de él, 404 y no 403.

    Por omisión **no** alcanza a los archivados: archivar es la única forma de
    retirar un documento del expediente, así que tiene que cortar el acceso de
    verdad, no solo quitarlo de la lista. Solo la pantalla de archivado pide
    `include_archived=True`, para poder decir «ya estaba archivado».
    """
    return get_object_or_404(
        documents_visible_for(user, include_archived=include_archived), public_id=public_id
    )


def documents_for(user, employee) -> QuerySet[EmployeeDocument]:
    return documents_visible_for(user).filter(employee=employee).order_by("-created_at")


def can_open(user, document: EmployeeDocument) -> bool:
    """Si este usuario puede abrir el **contenido**, no solo ver que existe."""
    if not user.is_authenticated:
        return False
    if not document.document_type.is_sensitive:
        return True
    return user.has_perm("documents.view_sensitive_document")


def uploadable_types_for(user, employee) -> QuerySet[DocumentType]:
    """Tipos que este usuario puede subir a esa ficha.

    RRHH sube cualquier tipo activo. La persona, solo los que el catálogo marca
    como suyos —un diploma, una constancia—, y solo a su propia ficha: el resto
    del expediente lo arma RRHH (§J.2, «P (tipos permitidos)»).
    """
    types = types_visible_for(user).filter(is_active=True).order_by("name")
    if user.has_perm("documents.change_employeedocument"):
        return types
    is_own = employee.user_id is not None and employee.user_id == user.pk
    if not is_own:
        return types.none()
    # Nunca un tipo confidencial: la persona no podría volver a abrirlo, y el
    # expediente reservado lo arma RRHH (§J.2).
    return types.filter(employee_can_upload=True).exclude(is_sensitive=True)


def expiring_soon(user, *, days: int = EXPIRY_WARNING_DAYS) -> QuerySet[EmployeeDocument]:
    """Documentos con vencimiento a la vista, incluidos los ya vencidos.

    Mismo patrón que «Contratos por terminar» del inicio de RRHH (UX §4.2).
    """
    today = timezone.localdate()
    return (
        documents_visible_for(user)
        .filter(expires_on__isnull=False, expires_on__lte=today + dt.timedelta(days=days))
        .order_by("expires_on")
    )
