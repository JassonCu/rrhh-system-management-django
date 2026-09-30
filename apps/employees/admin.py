from django.contrib import admin

from apps.employees.models import (
    Address,
    ContactMethod,
    EmergencyContact,
    Employee,
    IdentityDocument,
    Person,
)


class IdentityDocumentInline(admin.TabularInline):
    model = IdentityDocument
    extra = 0
    # El número se muestra completo solo aquí, en el admin, reservado a
    # SUPERADMIN. Las pantallas de la aplicación lo enmascaran (§G.19).
    readonly_fields = ("created_at", "updated_at")


class ContactMethodInline(admin.TabularInline):
    model = ContactMethod
    extra = 0


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "nationality")
    search_fields = ("first_name", "last_name", "second_last_name")
    inlines = [IdentityDocumentInline, ContactMethodInline, AddressInline]
    readonly_fields = ("created_at", "updated_at")


class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 0


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "person", "employment_status", "hire_date", "user")
    list_filter = ("employment_status",)
    search_fields = ("employee_code", "person__first_name", "person__last_name")
    list_select_related = ("person", "user")
    inlines = [EmergencyContactInline]
    readonly_fields = ("public_id", "created_at", "updated_at")
