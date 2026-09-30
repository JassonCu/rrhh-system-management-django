"""Declaración de roles y permisos.

Los roles se implementan como ``auth.Group``. Esta declaración es la **fuente de
verdad**: un receptor de ``post_migrate`` la aplica en cada `migrate`, de modo que
el estado converge siempre a lo declarado aquí.

**Por qué un receptor y no una migración de datos:** una migración captura el
estado en un punto del tiempo y no se vuelve a ejecutar, así que un grupo editado
a mano en el admin quedaría divergente para siempre. Además, los permisos los
crea ``post_migrate`` de ``contenttypes``/``auth`` *después* de aplicar las
migraciones, de modo que una migración de datos que los busque falla en una base
nueva. El receptor evita ambos problemas y sigue siendo idempotente y versionado.

Ver docs/security/10-autorizacion.md §J.1 y §J.2.
"""

from __future__ import annotations

from apps.accounts.constants import Role

__all__ = ["INCOMPATIBLE_ROLES", "NEVER_GRANTED", "ROLE_PERMISSIONS", "Role"]


#: Roles incompatibles entre sí. `AUDITOR` no puede combinarse con ningún rol de
#: escritura: sería una separación de funciones rota (§J.1).
INCOMPATIBLE_ROLES: dict[str, frozenset[str]] = {
    Role.AUDITOR: frozenset(
        {Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.MANAGER, Role.EMPLOYEE}
    ),
}

#: Permisos por rol, como ``"app_label.codename"``.
#:
#: Solo se listan los permisos de modelos que **ya existen**. Al añadir una app en
#: una fase posterior se amplía este mapa, y el siguiente `migrate` lo aplica.
#:
#: `SUPERADMIN` aparece con el conjunto vacío a propósito: su capacidad proviene
#: de ``is_superuser``, no de permisos explícitos. El grupo existe para poder
#: identificar a esos usuarios en la interfaz.
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    Role.SUPERADMIN: (),
    Role.HR_ADMIN: (
        "contracts.view_employmentcontract",
        "contracts.add_employmentcontract",
        "contracts.change_employmentcontract",
        "contracts.terminate_contract",
        "contracts.view_salary",
        "contracts.change_salary",
        "contracts.view_assignment",
        "contracts.add_assignment",
        "contracts.change_assignment",
        "accounts.view_user",
        "accounts.manage_users",
        "core.view_company",
        "core.add_company",
        "core.change_company",
        "core.view_holiday",
        "core.add_holiday",
        "core.change_holiday",
        "core.delete_holiday",
        "departments.view_department",
        "departments.add_department",
        "departments.change_department",
        # Las jefaturas salen del admin de Django en la entrega UX-3.
        "departments.view_departmentheadship",
        "departments.add_departmentheadship",
        "departments.change_departmentheadship",
        "positions.view_position",
        "positions.add_position",
        "positions.change_position",
        "positions.view_jobgrade",
        "positions.add_jobgrade",
        "positions.change_jobgrade",
        "employees.view_employee",
        "employees.add_employee",
        "employees.change_employee",
        "employees.view_sensitive_pii",
        # Asistencia (Fase 5)
        "attendance.view_workschedule",
        "attendance.add_workschedule",
        "attendance.change_workschedule",
        "attendance.view_scheduleassignment",
        "attendance.add_scheduleassignment",
        "attendance.view_attendanceentry",
        "attendance.add_attendanceentry",
        "attendance.adjust_attendance",
        "attendance.view_attendanceincident",
        "attendance.change_attendanceincident",
        # Ausencias (Fase 6)
        "leave.view_leavetype",
        "leave.add_leavetype",
        "leave.change_leavetype",
        "leave.view_leaverequest",
        "leave.add_leaverequest",
        "leave.change_leaverequest",
        "leave.approve_leave",
        "leave.view_leaveentitlement",
        "leave.add_leaveentitlement",
        "leave.view_leaveledgerentry",
        # Solo HR_ADMIN ajusta saldos a mano: mueve derechos de la persona.
        "leave.add_leaveledgerentry",
        "leave.view_leaverequesttransition",
        # Tramos por antigüedad: configuración del catálogo, auditada.
        "leave.view_leaveaccrualtier",
        "leave.add_leaveaccrualtier",
        "leave.delete_leaveaccrualtier",
        # Documentos (Fase 7)
        "documents.view_documenttype",
        "documents.add_documenttype",
        "documents.change_documenttype",
        "documents.view_employeedocument",
        "documents.add_employeedocument",
        "documents.change_employeedocument",
        # Los confidenciales (expedientes médicos) solo los abre RRHH y auditoría.
        "documents.view_sensitive_document",
        "documents.archive_document",
    ),
    Role.HR_MANAGER: (
        "contracts.view_employmentcontract",
        "contracts.view_assignment",
        "contracts.add_assignment",
        "contracts.change_assignment",
        "core.view_company",
        "core.view_holiday",
        "departments.view_department",
        # Ve los puestos pero NO las bandas salariales: es el "T (sin banda)" de
        # la matriz §J.2. La plantilla oculta el importe sin `view_jobgrade`.
        "positions.view_position",
        "employees.view_employee",
        "employees.add_employee",
        "employees.change_employee",
        "employees.view_sensitive_pii",
        # Asistencia: opera el día a día, incluidos ajustes e incidencias.
        "attendance.view_workschedule",
        "attendance.view_scheduleassignment",
        "attendance.add_scheduleassignment",
        "attendance.view_attendanceentry",
        "attendance.add_attendanceentry",
        "attendance.adjust_attendance",
        "attendance.view_attendanceincident",
        "attendance.change_attendanceincident",
        # Ausencias: opera y aprueba, pero no ajusta saldos a mano.
        "leave.view_leavetype",
        "leave.view_leaverequest",
        "leave.add_leaverequest",
        "leave.change_leaverequest",
        "leave.approve_leave",
        "leave.view_leaveentitlement",
        "leave.view_leaveledgerentry",
        "leave.view_leaverequesttransition",
        "leave.view_leaveaccrualtier",
        # Documentos: sube y consulta, pero **no** abre los confidenciales ni
        # archiva; eso queda en RRHH administración (§J.2).
        "documents.view_documenttype",
        "documents.view_employeedocument",
        "documents.add_employeedocument",
        "documents.change_employeedocument",
    ),
    Role.MANAGER: (
        "contracts.view_assignment",
        "core.view_company",
        "core.view_holiday",
        "departments.view_department",
        # Ve fichas de su equipo, pero NO su PII sensible: sin `view_sensitive_pii`
        # el DPI y la fecha de nacimiento le llegan enmascarados (§J.2).
        "employees.view_employee",
        # Asistencia de su equipo: la ve, la ajusta y resuelve incidencias. El
        # alcance lo limita a su departamento (§J.2).
        "attendance.view_attendanceentry",
        "attendance.add_attendanceentry",
        "attendance.adjust_attendance",
        "attendance.view_attendanceincident",
        "attendance.change_attendanceincident",
        # Ausencias de su equipo: las ve y las aprueba. El alcance y RN-44 los
        # impone el selector `can_approve`, no el permiso.
        "leave.view_leavetype",
        "leave.view_leaverequest",
        "leave.add_leaverequest",
        "leave.approve_leave",
        "leave.view_leaveledgerentry",
    ),
    Role.EMPLOYEE: (
        "contracts.view_employmentcontract",
        "contracts.view_salary",
        "contracts.view_assignment",
        "core.view_holiday",
        "departments.view_department",
        # El alcance lo limita a su propia ficha; el permiso solo abre la vista.
        "employees.view_employee",
        # Marca su propia asistencia y consulta sus incidencias.
        "attendance.view_attendanceentry",
        "attendance.add_attendanceentry",
        "attendance.view_attendanceincident",
        # Solicita sus ausencias y consulta su saldo.
        "leave.view_leavetype",
        "leave.view_leaverequest",
        "leave.add_leaverequest",
        "leave.view_leaveentitlement",
        "leave.view_leaveledgerentry",
        # Su propio expediente. Sin `change_employeedocument`, el selector solo
        # le ofrece los tipos que el catálogo marca como suyos.
        "documents.view_documenttype",
        "documents.view_employeedocument",
        "documents.add_employeedocument",
    ),
    Role.AUDITOR: (
        "contracts.view_employmentcontract",
        "contracts.view_salary",
        "contracts.view_assignment",
        "accounts.view_user",
        "core.view_company",
        "core.view_holiday",
        "departments.view_department",
        "positions.view_position",
        "positions.view_jobgrade",
        "employees.view_employee",
        "employees.view_sensitive_pii",
        # Auditoría: lo ve todo, no escribe nada.
        "attendance.view_workschedule",
        "attendance.view_scheduleassignment",
        "attendance.view_attendanceentry",
        "attendance.view_attendanceincident",
        "leave.view_leavetype",
        "leave.view_leaverequest",
        "leave.view_leaveentitlement",
        "leave.view_leaveledgerentry",
        "leave.view_leaverequesttransition",
        "leave.view_leaveaccrualtier",
        "documents.view_documenttype",
        "documents.view_employeedocument",
        "documents.view_sensitive_document",
        "audit.view_auditevent",
        "audit.view_audit_log",
    ),
}

#: Permisos que **nunca** se otorgan a ningún grupo, ni por descuido ni por
#: conveniencia. La prueba `test_forbidden_permissions_are_never_granted` lo
#: verifica sobre el estado real de la base (§J.3).
NEVER_GRANTED: frozenset[str] = frozenset(
    {
        # Un contrato activado es un hecho jurídico; el historial salarial y las
        # asignaciones se cierran, nunca se borran.
        "contracts.delete_employmentcontract",
        "contracts.delete_assignment",
        "audit.change_auditevent",  # no existen: default_permissions lo impide
        "audit.delete_auditevent",
        "accounts.delete_user",  # las cuentas se desactivan, no se borran
        "core.delete_company",
        # Los catálogos se desactivan; borrarlos rompería el histórico.
        "departments.delete_department",
        "positions.delete_position",
        "positions.delete_jobgrade",
        # Los empleados nunca se borran: se dan de baja (§E.3).
        "employees.delete_employee",
        "employees.delete_person",
        # Un expediente es prueba: se archiva con motivo, nunca se borra.
        "documents.delete_employeedocument",
        "documents.delete_documenttype",
    }
)
