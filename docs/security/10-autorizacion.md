# J. Autorización

> **Autenticado ≠ autorizado.** Cada vista responde tres preguntas, en este orden:
> ¿quién eres? (autenticación) · ¿puedes hacer esto? (permiso) · ¿puedes hacerlo
> **sobre este objeto**? (alcance).

---

## J.1 Roles

Se implementan como `auth.Group` de Django, poblados por una migración de datos
idempotente (no por fixtures manuales, que se olvidan de aplicar en producción).

| Rol | Descripción | Alcance de datos |
|---|---|---|
| `SUPERADMIN` | Administración técnica. `is_superuser` | Todo. **Solo por consola**; no se otorga desde la interfaz |
| `HR_ADMIN` | Responsable de RRHH. Gestiona empleados, contratos, salarios, documentos y catálogos | Toda la organización |
| `HR_MANAGER` | Analista de RRHH. Opera el día a día sin tocar catálogos ni salarios | Toda la organización, **sin** datos salariales |
| `MANAGER` | Jefe de departamento | **Solo su departamento y descendientes**, sin datos salariales |
| `EMPLOYEE` | Cualquier colaborador | **Solo sus propios datos** |
| `AUDITOR` | Cumplimiento / auditoría interna | Lectura de todo, incluida la bitácora. **Sin escritura en ningún caso** |

**Reglas de asignación:**

- Los roles no son excluyentes salvo por convención; un `MANAGER` es también
  `EMPLOYEE` (tiene su propio expediente).
- `AUDITOR` **no** se combina con roles de escritura: sería una separación de
  funciones rota. La comprobación se hace al asignar el grupo.
- Cambiar los grupos de un usuario es una acción auditada (`ROLE_CHANGE`) que
  invalida sus sesiones activas.

---

## J.2 Matriz de permisos

`P` = propio · `D` = su departamento (y descendientes) · `T` = toda la
organización · `—` = sin acceso.

| Recurso / acción | SUPERADMIN | HR_ADMIN | HR_MANAGER | MANAGER | EMPLOYEE | AUDITOR |
|---|---|---|---|---|---|---|
| Empleado — ver ficha básica | T | T | T | D | P | T |
| Empleado — ver PII sensible (DPI, fecha de nacimiento) | T | T | T | — | P | T |
| Empleado — crear / editar | T | T | T | — | — | — |
| Empleado — editar contacto propio | — | T | T | — | P | — |
| Empleado — cambiar de estado (baja, **solo terminando su contrato**) | T | T | — | — | — | — |
| Departamento — ver | T | T | T | D | T (nombre) | T |
| Departamento — crear / editar | T | T | — | — | — | — |
| Puesto y banda salarial — ver | T | T | T (sin banda) | — | — | T |
| Puesto y banda salarial — crear / editar | T | T | — | — | — | — |
| Contrato — ver | T | T | T | — | P | T |
| Contrato — crear / editar / terminar | T | T | — | — | — | — |
| **Salario — ver** | T | T | **—** | **—** | **P** | T |
| **Salario — modificar** | T | T | — | — | — | — |
| Asignación — ver | T | T | T | D | P | T |
| Asignación — crear / finalizar | T | T | T | — | — | — |
| Asistencia — ver | T | T | T | D | P | T |
| Asistencia — registrar marcaje | — | T | T | D | P | — |
| Asistencia — ajustar / justificar | T | T | T | D | — | — |
| Ausencia — solicitar | — | P | P | P | P | — |
| Ausencia — ver | T | T | T | D | P | T |
| Ausencia — aprobar / rechazar | T | T | T | D (≠ propia) | — | — |
| Saldo de ausencias — ver | T | T | T | D | P | T |
| Documento — ver / descargar | T | T | T (no sensibles) | — | P (no confidenciales de RRHH) | T |
| Documento — subir | T | T | T | — | P (tipos permitidos) | — |
| Documento — eliminar | T | T | — | — | — | — |
| Nómina — ver recibo | T | T | — | — | P | T |
| Nómina — ejecutar corrida | T | T | — | — | — | — |
| Bitácora de auditoría — ver | T | — | — | — | — | **T** |
| Usuarios y roles — gestionar | T | Invitar/desactivar | — | — | — | — |
| Admin de Django | T | — | — | — | — | — |

**Decisiones que conviene destacar:**

1. **`MANAGER` no ve salarios.** Es el hallazgo más común en sistemas de RRHH: se
   asume que un jefe puede ver todo de su equipo. Si el negocio requiere lo
   contrario, se creará un permiso separado (`view_team_salary`) asignable a
   jefaturas concretas, nunca al rol completo.
2. **`HR_MANAGER` no ve salarios** por defecto, por el mismo principio de mínimo
   privilegio (regla 36). Se separa el rol operativo del rol con acceso a
   compensación.
3. **`AUDITOR` no escribe nada**, ni siquiera su propio perfil, y es el único rol
   que lee la bitácora aparte de `SUPERADMIN`.
4. **`HR_ADMIN` no lee la bitácora.** Quien opera el sistema no debería poder
   revisar (ni presionar sobre) el registro que lo vigila.
5. **Nadie modifica su propia relación laboral**, tenga el rol que tenga,
   `SUPERADMIN` incluido. La matriz dice **qué** puede hacer cada rol; esta regla
   dice **sobre quién** no puede hacerlo. Se aplica en `contracts.services`, no en
   las vistas, para que ningún camino la esquive (revisión de la Fase 4, H-1).
6. **Las consultas de salario de terceros se auditan** (`SALARY_VIEW`), igual
   que las de PII sensible. Consultar el propio salario no se registra.

---

## J.3 Permisos de Django

Se usan los permisos automáticos (`add_`, `change_`, `delete_`, `view_`) y se
añaden **permisos personalizados** en `Meta.permissions` donde el modelo por sí
solo no expresa la regla:

| Permiso | Modelo | Significado |
|---|---|---|
| `view_sensitive_pii` | `Employee` | Ver DPI, fecha de nacimiento, estado civil |
| `view_salary` | `ContractSalary` | Ver importes salariales |
| `change_salary` | `ContractSalary` | Registrar cambios salariales |
| `terminate_contract` | `EmploymentContract` | Terminar una relación laboral |
| `approve_leave` | `LeaveRequest` | Aprobar o rechazar ausencias |
| `adjust_attendance` | `AttendanceEntry` | Corregir marcajes |
| `view_sensitive_document` | `EmployeeDocument` | Acceder a tipos marcados sensibles |
| `manage_users` | `User` | Invitar y desactivar cuentas |
| `view_audit_log` | `AuditEvent` | Consultar la bitácora |

**Nunca se otorgan** a ningún grupo: `change_auditevent`, `delete_auditevent`,
`delete_employee`, `delete_employmentcontract` (más allá de `DRAFT`),
`delete_payslip`.

---

## J.4 Autorización a nivel de objeto

No se usa `django-guardian` ni ACLs por fila: el alcance es **calculable** a
partir de las relaciones existentes, y una tabla de permisos por objeto sería
complejidad sin beneficio (regla 56).

El mecanismo es un **selector que acota el queryset**:

```
selectors.employees_visible_for(user) -> QuerySet[Employee]
    SUPERADMIN / HR_* / AUDITOR  → todos
    MANAGER                      → los que tienen una Assignment vigente sobre un
                                   puesto de un departamento que el usuario jefea
                                   hoy (incluyendo el subárbol), + él mismo
                                   → filter(position__department__in=…) (ADR-011)
    EMPLOYEE                     → solo él mismo
    sin rol                      → queryset vacío
```

Toda vista de empleados —lista, detalle, edición, exportación, documentos— parte
**del mismo selector**. Un detalle inaccesible no produce 403 sino **404**, para
no confirmar la existencia del recurso.

Selectores análogos: `contracts_visible_for`, `leave_requests_visible_for`,
`documents_visible_for`, `attendance_visible_for`.

**Por qué esto elimina el IDOR (regla 32):** la vista nunca hace
`Employee.objects.get(pk=...)`. Hace
`get_object_or_404(employees_visible_for(request.user), public_id=...)`. Cambiar
el identificador en la URL no amplía el conjunto visible, porque el filtro se
aplica **antes** de la búsqueda. El UUID de la URL dificulta la enumeración pero
**no es** el control de acceso (regla 22).

### Cascada de permisos con datos anidados

Un `MANAGER` que puede ver a un empleado **no** hereda automáticamente acceso a
sus documentos ni a su salario. Cada selector aplica su propia regla; no existe
"si puedes ver al padre, puedes ver a los hijos".

---

## J.5 Prevención de escalada de privilegios

| Vector | Mitigación |
|---|---|
| *Mass assignment* de `is_staff` / `is_superuser` / `groups` | **Ningún `ModelForm` del proyecto incluye estos campos.** Prohibido `fields = "__all__"` (regla 39); los campos se declaran uno a uno. Test que recorre todos los formularios y falla si aparece un campo prohibido o un `__all__` |
| Un usuario se asigna un rol a sí mismo | Solo `SUPERADMIN` cambia grupos; el servicio rechaza que un actor modifique sus propios grupos |
| `HR_ADMIN` se concede `view_audit_log` | Los permisos se asignan **por grupo desde una migración**; conceder permisos individuales a un usuario está deshabilitado en la interfaz |
| Modificar el `employee_id` de un formulario para editar a otro | El `queryset` de todo `ModelChoiceField` se acota con el selector del usuario; además el servicio revalida la propiedad del objeto |
| Aprobarse la propia ausencia | RN-44: el servicio compara solicitante y aprobador y rechaza. Es un test de seguridad, no solo de negocio |
| Sesión activa tras revocar el rol | El cambio de grupos invalida las sesiones del usuario |
| Acceso al admin de Django | Solo `SUPERADMIN` tiene `is_staff`. El admin no es el CRUD del negocio |

---

## J.6 Cómo se aplica en el código

```
@login_required
@permission_required("contracts.view_salary", raise_exception=True)
def salary_history(request, public_id):
    contract = get_object_or_404(
        selectors.contracts_visible_for(request.user),   # ← alcance
        public_id=public_id,
    )
    ...
```

Tres capas, siempre en este orden:

1. **Autenticación** — `@login_required` / `LoginRequiredMixin`.
2. **Permiso** — `@permission_required(..., raise_exception=True)`. El
   `raise_exception=True` es obligatorio: sin él, Django redirige al login y un
   usuario autenticado sin permiso entra en un bucle confuso en lugar de recibir
   un 403.
3. **Alcance** — selector + `get_object_or_404`.

**Prohibido explícitamente:**

- Comprobar permisos únicamente en la plantilla.
- `Model.objects.get(pk=request.GET["id"])` en una vista.
- Confiar en que un botón oculto impide la acción (regla 36).
- `@csrf_exempt` sin ADR que lo justifique.

### Decoradores de rol

`apps.accounts.decorators` ofrece además `@is_admin`, `@is_hr`, `@is_manager`,
`@is_employee`, `@is_auditor`, `@is_superadmin` y el genérico `@role_required`,
que responden a una pregunta **distinta** de la del permiso: no *qué se puede
hacer*, sino *quién entra a esta pantalla*.

```
@is_admin
def administration_console(request):
    ...
```

**Cuándo usar cada cosa:**

| La regla es… | Se escribe |
|---|---|
| «esta acción exige este permiso» | `@permission_required(..., raise_exception=True)` |
| «esta pantalla es de este rol» | `@is_admin`, `@is_manager`… |
| «este rol y además este permiso» | los dos, apilados: se exigen ambos |

**La prueba para decidir:** si al añadir un rol nuevo con los permisos
adecuados habría que **editar la vista**, entonces el criterio correcto era el
permiso, no el rol. Un decorador de rol congela la matriz §J.2 dentro del
código, y por eso se reserva para las pantallas donde el rol *es* el criterio.

**Lo que garantizan:** sin sesión redirigen al acceso, con sesión y rol
insuficiente responden 403 y **registran el intento** (`PERMISSION_DENIED`), y
`is_superuser` pasa siempre salvo que se construyan con
`allow_superuser=False`. Los cubre `accounts/tests/test_decorators.py`.

**Lo que no hacen:** no aplican alcance. La tercera capa —el selector— sigue
siendo obligatoria igual que antes.

---

## J.7 Tests de autorización

Es la suite más importante del proyecto. Para **cada** vista sensible se prueba
la matriz completa:

| Caso | Resultado esperado |
|---|---|
| Anónimo | Redirección al login |
| Autenticado sin rol | 403 |
| `EMPLOYEE` sobre su propio recurso | 200 |
| `EMPLOYEE` sobre recurso ajeno | **404** (no 403: no se confirma la existencia) |
| `MANAGER` sobre su departamento | 200 |
| `MANAGER` sobre otro departamento | 404 |
| `MANAGER` sobre salario de su equipo | 403 |
| `HR_MANAGER` sobre salario | 403 |
| `HR_ADMIN` | 200 |
| `AUDITOR` en `GET` | 200 |
| `AUDITOR` en `POST`/`DELETE` | 403 |
| `POST` sin token CSRF | 403 |
| `POST` con campo prohibido (`is_superuser`, `groups`, `employee_id` ajeno) | El campo se ignora o la petición se rechaza; se verifica que el valor **no cambió** en la base |

Se implementa con `pytest.mark.parametrize` sobre `(rol, url, método,
código_esperado)`, de modo que añadir una vista sin añadir su fila haga fallar un
test de cobertura de la tabla de URLs. Objetivo declarado: **que sea imposible
publicar una vista sin decidir explícitamente quién puede usarla.**
