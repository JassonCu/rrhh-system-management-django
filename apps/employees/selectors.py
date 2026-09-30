"""Consultas de lectura con alcance de autorización (ADR-005).

**Este módulo es el corazón de la protección contra IDOR.** Toda vista de
empleados —lista, detalle, edición, documentos— parte de aquí, y ninguna hace
`Employee.objects.get(pk=...)` con un identificador de la URL: el filtro se
aplica **antes** de la búsqueda, de modo que cambiar el identificador no amplía
el conjunto visible (§J.4).
"""

from __future__ import annotations

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from apps.accounts.constants import Role
from apps.departments.selectors import departments_headed_by
from apps.employees.constants import ContactType
from apps.employees.models import Employee

#: Roles con visibilidad sobre toda la organización (§J.2).
ORGANIZATION_WIDE = frozenset({Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.AUDITOR})


def _roles_of(user) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def employees_visible_for(user) -> QuerySet[Employee]:
    """Empleados que este usuario puede ver.

    * RRHH y auditoría: toda la organización.
    * `MANAGER`: su equipo **y él mismo** (ver la nota sobre la Fase 4).
    * Cualquier otro: solo él mismo.
    * Anónimo o sin vínculo a un empleado: nada.

    El equipo de un `MANAGER` son los empleados con una asignación **vigente**
    sobre un puesto de un departamento que jefea hoy, incluido su subárbol, y
    con un contrato vivo. Un contrato terminado o una asignación cerrada sacan
    a la persona del alcance en el mismo momento.
    """
    base = Employee.objects.select_related("person", "user")

    if not user.is_authenticated:
        return Employee.objects.none()
    if user.is_superuser or (_roles_of(user) & ORGANIZATION_WIDE):
        return base

    own = Employee.objects.filter(user=user).values_list("pk", flat=True)
    visible_ids = set(own)

    if Role.MANAGER in _roles_of(user):
        headed = departments_headed_by(user)
        if headed:
            visible_ids |= _team_of(headed)

    return base.filter(pk__in=visible_ids)


def get_employee_or_404(user, *, public_id) -> Employee:
    """Obtiene un empleado **dentro del alcance** del actor.

    Fuera de alcance devuelve **404 y no 403**: un 403 confirmaría que el
    empleado existe, que es exactamente lo que un atacante quiere averiguar.
    """
    return get_object_or_404(employees_visible_for(user), public_id=public_id)


def can_view_sensitive_pii(user, employee: Employee) -> bool:
    """Si este usuario puede ver el DPI y la fecha de nacimiento sin enmascarar.

    Lo pueden RRHH (por permiso) y la propia persona (por ser suyo). Un
    `MANAGER` **no**, aunque vea la ficha: no hay cascada de permisos (§J.4).
    """
    if not user.is_authenticated:
        return False
    if user.has_perm("employees.view_sensitive_pii"):
        return True
    return employee.user_id is not None and employee.user_id == user.pk


def identity_documents_for(user, employee: Employee) -> QuerySet:
    """Documentos de identificación del empleado, ya acotados.

    Se consulta por separado y no por la relación inversa para que el alcance se
    aplique aquí y no dependa de que la plantilla recuerde filtrar.
    """
    if not employees_visible_for(user).filter(pk=employee.pk).exists():
        return employee.person.identity_documents.none()
    return employee.person.identity_documents.all()


def can_view_personal_data(user, employee: Employee) -> bool:
    """Si este usuario ve los datos personales no laborales de la ficha.

    Teléfonos y correos personales, direcciones y contactos de emergencia son
    PII (§G.19): los ven RRHH y la propia persona. Un `MANAGER` ve la ficha de su
    equipo pero **no** esto; solo el contacto laboral. La audiencia coincide hoy
    con la de la PII sensible, pero se expone como función propia para que las
    dos reglas puedan divergir sin tocar las vistas.
    """
    return can_view_sensitive_pii(user, employee)


def contact_methods_for(user, employee: Employee) -> QuerySet:
    """Contactos de la persona, acotados a lo que el usuario puede ver.

    Sin acceso a datos personales solo se devuelve el correo laboral: es lo que
    un jefe necesita para trabajar con alguien de su equipo.
    """
    contacts = employee.person.contact_methods.all()
    if not employees_visible_for(user).filter(pk=employee.pk).exists():
        return contacts.none()
    if can_view_personal_data(user, employee):
        return contacts
    return contacts.filter(contact_type=ContactType.WORK_EMAIL)


def emergency_contacts_for(user, employee: Employee) -> QuerySet:
    """Contactos de emergencia: PII de terceros, solo para RRHH y la propia persona."""
    contacts = employee.emergency_contacts.all()
    if not employees_visible_for(user).filter(pk=employee.pk).exists():
        return contacts.none()
    return contacts if can_view_personal_data(user, employee) else contacts.none()


def _team_of(department_ids: set[int]) -> set[int]:
    """Empleados con una asignación vigente en esos departamentos.

    La consulta vive en `contracts.selectors`, interfaz pública de esa app. Se
    importa aquí dentro y no a nivel de módulo porque `contracts` depende de
    `employees`: la importación diferida evita el ciclo al cargar las apps.
    """
    from apps.contracts.selectors import employee_ids_assigned_to

    return employee_ids_assigned_to(department_ids)
