from django.contrib import admin
from django.http import HttpRequest

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Solo lectura, por diseño.

    Refuerza en la interfaz lo que el modelo ya impide: la bitácora es
    append-only (RN-70). Los permisos change/delete ni siquiera existen.
    """

    list_display = ("occurred_at", "action", "outcome", "actor_repr", "object_type", "object_id")
    list_filter = ("action", "outcome", "occurred_at")
    search_fields = ("actor_repr", "object_repr", "object_id")
    date_hierarchy = "occurred_at"
    readonly_fields = tuple(f.name for f in AuditEvent._meta.fields)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AuditEvent | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AuditEvent | None = None) -> bool:
        return False
