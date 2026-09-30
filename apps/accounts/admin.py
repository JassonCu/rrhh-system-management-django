from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Admin de usuarios adaptado al login por correo.

    El admin es una herramienta de administración técnica reservada a
    SUPERADMIN, no el CRUD del negocio (§H.3).
    """

    ordering = ("email",)
    list_display = ("email", "is_active", "is_staff", "is_superuser", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "language")
    search_fields = ("email",)
    readonly_fields = ("last_login", "date_joined", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Preferences"), {"fields": ("language", "must_change_password")}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("Audit"), {"fields": ("created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "language"),
            },
        ),
    )
