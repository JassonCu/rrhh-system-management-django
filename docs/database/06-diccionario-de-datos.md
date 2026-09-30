# G. Diccionario de datos

Documenta cada entidad con su propósito, claves, atributos, nulabilidad,
restricciones y reglas de negocio asociadas (regla 25).

**Alcance de detalle.** Las entidades de las fases 1–4 y de auditoría se
documentan por completo, porque son las que se implementarán primero. Las de las
fases 5–8 se documentan a nivel de contrato de esquema (atributos, claves y
restricciones ya constan en [B. Modelo relacional](02-modelo-relacional.md) y en
el [ERD](05-erd.md)); su diccionario completo se redactará al abrir cada fase, y
**esta es la política declarada, no un olvido**.

---

## G.0 Convenciones comunes

### Campos de auditoría técnica

Toda entidad **mutable** hereda del modelo abstracto `TimeStampedModel`:

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `created_at` | `DateTimeField(auto_now_add=True)` | No | Instante de creación, UTC |
| `updated_at` | `DateTimeField(auto_now=True)` | No | Instante de última modificación, UTC |

Las entidades **append-only** (`AuditEvent`, `LeaveLedgerEntry`,
`LeaveRequestTransition`, `AttendanceEntry`) llevan solo `created_at` /
`occurred_at`: no se modifican, luego `updated_at` sería siempre igual y mentiría
sobre la inmutabilidad.

### Tipos y su correspondencia SQLite → PostgreSQL

| Django | SQLite | PostgreSQL | Nota de migración |
|---|---|---|---|
| `BigAutoField` | `INTEGER` | `bigint` | Transparente |
| `UUIDField` | `char(32)` | `uuid` | Django gestiona la conversión |
| `CharField(n)` | `varchar(n)` | `varchar(n)` | — |
| `DecimalField(m,d)` | `decimal` (almacenado como texto/real) | `numeric(m,d)` | **SQLite no valida la precisión.** Los tests de dinero deben ejecutarse también contra PostgreSQL antes de producción |
| `DateField` / `DateTimeField` | `date` / `datetime` | `date` / `timestamptz` | `USE_TZ=True` desde el inicio evita la trampa clásica |
| `JSONField` | `text` con JSON1 | `jsonb` | No usar operadores específicos de un motor en consultas |
| `BooleanField` | `bool` (0/1) | `boolean` | — |

**Regla:** no se usan tipos ni funciones específicas de SQLite (regla 26). Toda
consulta se expresa con el ORM; `RawSQL` requiere aprobación explícita en revisión.

### Convención de dinero

Todo importe monetario es `DecimalField(max_digits=12, decimal_places=2)` con un
campo `currency` `CharField(3)` adyacente. **Nunca `FloatField`.** Doce dígitos
admiten hasta 9 999 999 999.99 en cualquier moneda razonable.

### Convención de internacionalización

Todo modelo declara `verbose_name` y `verbose_name_plural` traducibles en su
`Meta`, y todo campo lleva `verbose_name` y, cuando la regla no sea evidente,
`help_text`, siempre con `gettext_lazy`. **El valor almacenado de un `choices`
nunca se traduce; solo su etiqueta.** El detalle y sus motivos están en
[O. Internacionalización](../architecture/14-internacionalizacion.md); por brevedad,
las tablas de este diccionario no repiten los `verbose_name` de cada columna.

### Convención de choices

Los conjuntos cerrados se declaran con `models.TextChoices` y se refuerzan con
`CheckConstraint`. Motivo: `choices` solo valida en `full_clean()`, que no se
ejecuta en `Model.objects.create()`, `bulk_create()` ni `update()`. Sin el
constraint, un estado inválido entra a la base sin resistencia (regla 20).

---

## G.1 `core.Company`

**Propósito:** entidad legal empleadora. Con una sola fila en el escenario
inicial; existe para no hacer costosa la evolución multi-empresa (ver A.5).

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `code` | `CharField(20)` | No | Sí | Código interno corto |
| `legal_name` | `CharField(200)` | No | No | Razón social |
| `trade_name` | `CharField(200)` | Sí | No | Nombre comercial |
| `tax_id` | `CharField(20)` | No | Sí | NIT patronal |
| `country` | `CharField(2)` | No | No | ISO-3166-1 alfa-2 |
| `is_active` | `BooleanField` | No | No | Por defecto `True` |

- **PK:** `id` · **FK:** ninguna · **CK:** `{id}`, `{code}`, `{tax_id}`
- **Relaciones:** 1:N con `Department`, `EmploymentContract`, `Holiday`
- **Reglas:** no se elimina nunca (`PROTECT` desde todas las FKs)

## G.2 `core.Holiday`

**Propósito:** feriados oficiales; insumo del cálculo de días hábiles (RN-42).

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `company_id` | `FK(Company, PROTECT)` | No | UK(1/2) | — |
| `date` | `DateField` | No | UK(2/2) | — |
| `name` | `CharField(120)` | No | No | Ej. "Día de la Independencia" |
| `is_mandatory` | `BooleanField` | No | No | Distingue asueto de ley de asueto interno |

- **CK:** `{id}`, `{company_id, date}` · **UQ:** `(company_id, date)`
- **Índice:** `(company_id, date)` — cubierto por el `UniqueConstraint`

---

## G.3 `accounts.User`

**Propósito:** credencial de acceso. **No** contiene datos de recursos humanos.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `email` | `EmailField(254)` | No | Sí | `USERNAME_FIELD`. Normalizado a minúsculas en `save()` |
| `password` | `CharField(128)` | No | No | Hash gestionado por Django. **Nunca se lee ni se registra** |
| `is_active` | `BooleanField` | No | No | Desactivar en lugar de eliminar |
| `is_staff` | `BooleanField` | No | No | Acceso al admin. Por defecto `False` |
| `is_superuser` | `BooleanField` | No | No | Por defecto `False`. Solo se asigna por consola |
| `must_change_password` | `BooleanField` | No | No | Fuerza el cambio tras alta o reseteo por RRHH |
| `language` | `CharField(10)` | No | No | Idioma preferido. Choices = `LANGUAGES`; por defecto `es-gt`. Ver [O. Internacionalización](../architecture/14-internacionalizacion.md) |
| `last_login` | `DateTimeField` | Sí | No | Gestionado por Django |
| `date_joined` | `DateTimeField` | No | No | — |

- **CK:** `{id}`, `{email}` · **Relaciones:** 0..1 con `Employee`; 1:N con `AuditEvent`, `EmployeeDocument`
- **Reglas:**
  - RN-S1: la baja de un usuario es `is_active = False`; **nunca `DELETE`**, para
    no perder la trazabilidad de sus acciones.
  - RN-S2: `is_staff` e `is_superuser` **jamás** aparecen en un `ModelForm` de la
    aplicación (prevención de escalada de privilegios, regla 39).
  - Los roles se expresan mediante `Group`, no con columnas booleanas propias.

## G.3b `accounts.AccountActivationCode` (Fase 6)

**Propósito:** token de un solo uso que RRHH entrega en mano para que una persona
sin correo corporativo active su cuenta
([ADR-004](../decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md)).

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `user_id` | `FK(User, CASCADE)` | No | Parcial | Único donde `status = 'PENDING'` |
| `code_hash` | `CharField(64)` | No | Sí | `HMAC-SHA256(código, SECRET_KEY)` en hexadecimal. **El código en claro nunca se persiste** |
| `status` | `CharField(10)` | No | No | Choices: `PENDING`, `REDEEMED`, `REVOKED` |
| `expires_at` | `DateTimeField` | No | No | Por defecto, 72 h desde la emisión |
| `resolved_at` | `DateTimeField` | Sí | No | Instante del canje o la revocación |
| `created_by_id` | `FK(User, SET_NULL)` | Sí | No | Quién lo emitió |
| `created_at` | `DateTimeField` | No | No | — |

- **CK:** `{id}`, `{code_hash}`
- **UQ:** `code_hash` · **UQ parcial:** `(user_id)` donde `status = 'PENDING'`
- **CH:** `status` ∈ choices; `expires_at > created_at`;
  `(status = 'PENDING') = (resolved_at IS NULL)`
- **Sin `updated_at`:** la fila cambia una sola vez, de `PENDING` a su estado
  final, y `resolved_at` ya registra ese instante
- **Caducidad:** no es un estado. Un código `PENDING` con `expires_at` en el
  pasado se rechaza por comparación de fechas; no hay proceso periódico que
  reescriba filas
- **Clasificación:** **restringido.** El hash no se muestra en ninguna interfaz ni
  se registra en logs; el código en claro existe solo en memoria durante la
  petición que lo genera
- **Índices:** `code_hash` (único, es la vía de búsqueda del canje);
  `(user_id, status)`

---

## G.4 `employees.Person`

**Propósito:** identidad civil de una persona física.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `first_name` | `CharField(60)` | No | No | Primer nombre |
| `middle_name` | `CharField(60)` | Sí | No | Segundo nombre |
| `last_name` | `CharField(60)` | No | No | Primer apellido |
| `second_last_name` | `CharField(60)` | Sí | No | Segundo apellido |
| `birth_date` | `DateField` | No | No | RN-04 |
| `gender` | `CharField(20)` | No | No | Choices: `FEMALE`, `MALE`, `OTHER`, `UNDISCLOSED` |
| `marital_status` | `CharField(20)` | No | No | Choices: `SINGLE`, `MARRIED`, `DIVORCED`, `WIDOWED`, `PARTNERED`, `UNDISCLOSED` |
| `nationality` | `CharField(2)` | No | No | ISO-3166-1 alfa-2 |

- **CK:** `{id}` (sin clave natural fiable)
- **CH:** `birth_date < CURRENT_DATE`; `gender` ∈ choices; `marital_status` ∈ choices
- **Campo ausente por diseño:** `full_name` (derivable; ver [§C.4](03-dependencias-funcionales.md#c4-employees))
- **Clasificación de datos:** **PII**. Toda la entidad está sujeta a control de
  acceso a nivel de objeto y no aparece en logs.

## G.5 `employees.IdentityDocument`

**Propósito:** documentos de identificación de una persona (DPI/CUI, NIT, IGSS,
pasaporte). Resuelve el atributo multivaluado.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `person_id` | `FK(Person, CASCADE)` | No | No | Pertenece al agregado `Person` |
| `document_type` | `CharField(20)` | No | UK(1/3) | Choices: `DPI`, `NIT`, `IGSS`, `PASSPORT`, `DRIVER_LICENSE` |
| `number` | `CharField(40)` | No | UK(2/3) | Normalizado: sin espacios ni guiones |
| `issuing_country` | `CharField(2)` | No | UK(3/3) | ISO-3166-1 alfa-2 |
| `issued_on` | `DateField` | Sí | No | — |
| `expires_on` | `DateField` | Sí | No | Nulo = no vence |
| `is_primary` | `BooleanField` | No | No | Documento de identificación principal |

- **CK:** `{id}`, `{document_type, number, issuing_country}`
- **UQ:** `(document_type, number, issuing_country)` — RN-02
- **UQ parcial:** `(person_id, document_type, issuing_country)` con
  `expires_on IS NULL OR expires_on >= hoy` — RN-03
- **CH:** `issued_on <= expires_on` cuando ambos existen
- **Validación de dominio:** formato de CUI (13 dígitos + verificador) y de NIT
  (módulo 11) en validadores de `employees.validators`, con pruebas propias
- **Clasificación:** **PII sensible.** El número se muestra enmascarado
  (`****3456`) salvo para RRHH y el propio empleado
- **Borrado:** `CASCADE` desde `Person` es seguro porque `Person` está protegida
  por `Employee` (`PROTECT`): en la práctica nunca se elimina una persona con
  vínculo laboral

## G.6 `employees.ContactMethod`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `person_id` | `FK(Person, CASCADE)` | No | UK(1/3) | — |
| `contact_type` | `CharField(20)` | No | UK(2/3) | Choices: `MOBILE`, `LANDLINE`, `PERSONAL_EMAIL`, `WORK_EMAIL` |
| `value` | `CharField(150)` | No | UK(3/3) | Teléfono normalizado E.164 o correo en minúsculas |
| `is_primary` | `BooleanField` | No | No | RN-05 |
| `notes` | `CharField(200)` | Sí | No | Ej. "solo por las tardes" |

- **UQ:** `(person_id, contact_type, value)`
- **UQ parcial:** `(person_id, contact_type)` donde `is_primary = TRUE`
- **Clasificación:** PII

## G.7 `employees.Address`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `person_id` | `FK(Person, CASCADE)` | No | No | — |
| `address_type` | `CharField(20)` | No | No | Choices: `HOME`, `MAILING` |
| `line1` | `CharField(200)` | No | No | Calle y número |
| `line2` | `CharField(200)` | Sí | No | Referencia, zona |
| `locality` | `CharField(100)` | No | No | Municipio (texto libre, ver A.6) |
| `region` | `CharField(100)` | No | No | Departamento/estado (texto libre) |
| `postal_code` | `CharField(20)` | Sí | No | — |
| `country` | `CharField(2)` | No | No | ISO-3166-1 alfa-2 |
| `is_primary` | `BooleanField` | No | No | RN-06 |

- **UQ parcial:** `(person_id)` donde `is_primary = TRUE`
- **Clasificación:** PII

## G.8 `employees.Employee`

**Propósito:** identidad laboral. Nodo central de relaciones, **no** depósito de
datos.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `public_id` | `UUIDField(v4)` | No | Sí | Identificador de URL. Indexado |
| `person_id` | `OneToOne(Person, PROTECT)` | No | Sí | 1:1 |
| `user_id` | `OneToOne(User, SET_NULL)` | Sí | Sí | 0..1. Nulo = empleado sin acceso al sistema |
| `employee_code` | `CharField(20)` | No | Sí | Clave natural. No se reutiliza (RN-01) |
| `hire_date` | `DateField` | No | No | Fecha de ingreso original |
| `employment_status` | `CharField(20)` | No | No | Choices: `ACTIVE`, `ON_LEAVE`, `SUSPENDED`, `TERMINATED` |
| `termination_date` | `DateField` | Sí | No | Solo si `employment_status = TERMINATED` |

- **CK:** `{id}`, `{public_id}`, `{employee_code}`, `{person_id}`
- **CH:**
  - `termination_date IS NULL OR termination_date >= hire_date` (RN-17)
  - `(employment_status = 'TERMINATED') = (termination_date IS NOT NULL)`
  - `employment_status` ∈ choices
- **Campos ausentes por diseño:** `department_id`, `position_id`, `salary`,
  `manager_id`, `contract_type` — todos viven en `contracts` con vigencia
- **Reglas:**
  - RN-18: `employment_status` solo se modifica desde `contracts.services`
  - **Nunca se elimina.** Toda FK hacia `Employee` usa `PROTECT`
- **Índices:** `public_id` (único), `employee_code` (único),
  `employment_status` (filtro dominante en el listado principal)

## G.9 `employees.EmergencyContact`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `employee_id` | `FK(Employee, CASCADE)` | No | UK(1/2) | — |
| `full_name` | `CharField(150)` | No | No | Persona externa al sistema |
| `relationship` | `CharField(30)` | No | No | Choices: `SPOUSE`, `PARENT`, `CHILD`, `SIBLING`, `FRIEND`, `OTHER` |
| `phone` | `CharField(30)` | No | No | E.164 |
| `alternate_phone` | `CharField(30)` | Sí | No | — |
| `priority` | `PositiveSmallIntegerField` | No | UK(2/2) | 1 = primer contacto |

- **UQ:** `(employee_id, priority)` · **CH:** `priority >= 1`
- **Clasificación:** PII de tercero. Visible solo para RRHH y el propio empleado

---

## G.10 `departments.Department`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `company_id` | `FK(Company, PROTECT)` | No | UK(1/2) | — |
| `parent_id` | `FK(self, PROTECT)` | Sí | No | Nulo = raíz del organigrama |
| `code` | `CharField(20)` | No | UK(2/2) | RN-30 |
| `name` | `CharField(120)` | No | No | **Fuente de verdad del nombre** |
| `cost_center` | `CharField(30)` | Sí | No | Enlace con contabilidad |
| `is_active` | `BooleanField` | No | No | Baja lógica justificada: el histórico lo referencia |

- **UQ:** `(company_id, code)` · **CH:** `parent_id <> id`
- **Reglas:** RN-31 (aciclicidad) y RN-33 (no desactivar con asignaciones
  vigentes) se validan en `departments.services`
- **Índices:** `(company_id, code)` único; `parent_id` (recorrido del árbol)
- **Soft delete justificado:** `is_active` en lugar de borrado, porque
  `Assignment` histórico apunta aquí y el nombre debe seguir resolviéndose

## G.11 `departments.DepartmentHeadship`

**Propósito:** jefatura con vigencia. Permite reconstruir la cadena de mando en
cualquier fecha pasada — requisito de la trazabilidad de aprobaciones.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `department_id` | `FK(Department, PROTECT)` | No | UK(1/2) | — |
| `employee_id` | `FK(Employee, PROTECT)` | No | No | Jefe designado |
| `start_date` | `DateField` | No | UK(2/2) | — |
| `end_date` | `DateField` | Sí | No | Nulo = jefatura vigente |
| `appointment_note` | `CharField(200)` | Sí | No | — |

- **UQ:** `(department_id, start_date)`
- **UQ parcial:** `(department_id)` donde `end_date IS NULL` — RN-32
- **CH:** `end_date IS NULL OR start_date <= end_date`
- **Índices:** `(employee_id, end_date)` — resuelve "¿qué departamentos jefea hoy
  este usuario?", consulta **crítica para la autorización** de la vista de
  MANAGER

---

## G.12 `positions.JobGrade`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `code` | `CharField(10)` | No | Sí | Ej. `G05` |
| `name` | `CharField(80)` | No | No | — |
| `level` | `PositiveSmallIntegerField` | No | No | Orden jerárquico |
| `min_salary` | `Decimal(12,2)` | No | No | RN-34 |
| `max_salary` | `Decimal(12,2)` | No | No | RN-34 |
| `currency` | `CharField(3)` | No | No | ISO-4217 |
| `is_active` | `BooleanField` | No | No | — |

- **CH:** `min_salary > 0`; `min_salary <= max_salary`; `level >= 1`
- **Clasificación:** confidencial. Solo RRHH ve las bandas salariales

## G.13 `positions.Position`

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `department_id` | `FK(Department, PROTECT)` | No | UK(1/2) | El puesto pertenece a un área ([ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md)) |
| `job_grade_id` | `FK(JobGrade, PROTECT)` | No | No | Única fuente del rango salarial |
| `code` | `CharField(20)` | No | Sí | Único en toda la organización |
| `title` | `CharField(120)` | No | UK(2/2) | **Fuente de verdad del título**. Único dentro del departamento (RN-35) |
| `description` | `TextField` | Sí | No | Perfil del puesto, **específico del área** |
| `is_active` | `BooleanField` | No | No | — |

- **CK:** `{id}`, `{code}`, `{department_id, title}`
- **UQ:** `code`; `(department_id, title)` — RN-35
- **Campo ausente por diseño:** `min_salary`/`max_salary` (3NF, §D.5.2); viven en
  `JobGrade`
- **Consecuencia operativa:** crear un departamento implica crear sus puestos. La
  reportería transversal por tipo de cargo exigiría agrupar por título; la salida
  documentada, si llega a requerirse, es una taxonomía `JobFamily`

---

## G.14 `contracts.EmploymentContract`

**Propósito:** relación laboral formal. Raíz del agregado más importante del
sistema.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `public_id` | `UUIDField(v4)` | No | Sí | Identificador de URL |
| `employee_id` | `FK(Employee, PROTECT)` | No | Parcial | Único donde `status IN (ACTIVE, SUSPENDED)` (RN-13: un suspendido sigue siendo un vínculo vivo) |
| `company_id` | `FK(Company, PROTECT)` | No | No | Entidad legal contratante |
| `contract_type` | `CharField(20)` | No | No | Choices: `INDEFINITE`, `FIXED_TERM`, `TEMPORARY`, `INTERNSHIP` |
| `start_date` | `DateField` | No | No | — |
| `end_date` | `DateField` | Sí | No | Obligatorio si `FIXED_TERM` (RN-12) |
| `probation_end_date` | `DateField` | Sí | No | RN-15 |
| `status` | `CharField(20)` | No | No | Choices: `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATED`, `EXPIRED` |
| `termination_reason` | `CharField(40)` | Sí | No | Choices: `RESIGNATION`, `DISMISSAL_WITH_CAUSE`, `DISMISSAL_WITHOUT_CAUSE`, `MUTUAL_AGREEMENT`, `CONTRACT_EXPIRY`, `RETIREMENT`, `DEATH` |
| `termination_date` | `DateField` | Sí | No | RN-16, RN-17 |
| `signed_on` | `DateField` | Sí | No | Fecha de firma física |
| `notes` | `TextField` | Sí | No | — |

- **UQ:** `public_id`; **UQ parcial:** `(employee_id)` donde `status = 'ACTIVE'`
- **CH:** las cinco listadas en [B.6](02-modelo-relacional.md)
- **Transiciones válidas de `status`:**

```
DRAFT ──► ACTIVE ──► SUSPENDED ──► ACTIVE
              │                       │
              └──────► TERMINATED ◄───┘
              └──────► EXPIRED  (automático al vencer end_date)
DRAFT ──► (eliminable solo en DRAFT, por HR_ADMIN, con auditoría)
```

- **Borrado:** solo se permite `DELETE` en estado `DRAFT`. Un contrato que llegó
  a `ACTIVE` es un hecho jurídico y **nunca** se elimina
- **Clasificación:** confidencial
- **Índices:** `(employee_id, status)`, `(status, end_date)` para el proceso de
  vencimientos, `public_id` único

## G.15 `contracts.ContractSalary`

**Propósito:** historial salarial. Cada fila es un hecho fechado e inmutable.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `contract_id` | `FK(EmploymentContract, PROTECT)` | No | UK(1/2) | — |
| `amount` | `Decimal(12,2)` | No | No | RN-22 |
| `currency` | `CharField(3)` | No | No | ISO-4217 |
| `pay_frequency` | `CharField(20)` | No | No | Choices: `MONTHLY`, `BIWEEKLY`, `WEEKLY` |
| `effective_from` | `DateField` | No | UK(2/2) | — |
| `effective_to` | `DateField` | Sí | No | Nulo = salario vigente |
| `change_reason` | `CharField(40)` | No | No | Choices: `INITIAL`, `MERIT_INCREASE`, `PROMOTION`, `ADJUSTMENT`, `LEGAL_MINIMUM`, `DEMOTION` |
| `created_by_id` | `FK(User, SET_NULL)` | Sí | No | Quién registró el cambio |

- **UQ:** `(contract_id, effective_from)`
- **UQ parcial:** `(contract_id)` donde `effective_to IS NULL` — RN-20
- **CH:** `amount > 0`; `effective_to IS NULL OR effective_from <= effective_to`
- **Inmutabilidad:** una vez cerrada (`effective_to` no nulo) la fila no se
  edita; una corrección se registra como nueva fila con `change_reason = ADJUSTMENT`
- **Clasificación:** **altamente confidencial.** Visible para RRHH y para el
  propio empleado; **nunca** para un MANAGER salvo permiso explícito
- **Índices:** `(contract_id, effective_from DESC)` — resuelve "salario vigente"

## G.16 `contracts.Assignment`

**Propósito:** entidad asociativa que ubica un contrato en un puesto y un
departamento durante un período.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `contract_id` | `FK(EmploymentContract, PROTECT)` | No | UK(1/3) | **No hay `employee_id`** (3NF, §D.5.3) |
| `position_id` | `FK(Position, PROTECT)` | No | UK(2/3) | **No hay `department_id`**: se deriva del puesto (3NF, §D.5.4) |
| `start_date` | `DateField` | No | UK(3/3) | RN-26 |
| `end_date` | `DateField` | Sí | No | Nulo = asignación vigente |
| `is_primary` | `BooleanField` | No | No | RN-24 |
| `fte` | `Decimal(3,2)` | No | No | RN-25. `1.00` = tiempo completo |
| `assignment_reason` | `CharField(40)` | No | No | Choices: `INITIAL`, `PROMOTION`, `TRANSFER`, `REORGANIZATION`, `TEMPORARY_COVER` |

- **UQ:** `(contract_id, position_id, start_date)`
- **UQ parcial:** `(contract_id)` donde `end_date IS NULL AND is_primary = TRUE`
- **CH:** `end_date IS NULL OR start_date <= end_date`; `fte > 0 AND fte <= 1.00`
- **Índices:** `(contract_id, end_date)` y `(position_id, end_date)`. El segundo,
  junto con `Position(department_id)`, es **crítico para la autorización**:
  resuelve "empleados vigentes del departamento X", que usa el alcance de MANAGER
  a través de `position__department`

---

## G.17 `audit.AuditEvent`

**Propósito:** registro append-only de eventos relevantes de seguridad y negocio.

| Campo | Tipo | Nulo | Único | Descripción / Regla |
|---|---|---|---|---|
| `id` | `BigAutoField` | No | PK | — |
| `occurred_at` | `DateTimeField(db_index=True)` | No | No | UTC |
| `actor_id` | `FK(User, SET_NULL)` | Sí | No | Nulo = sistema, o usuario eliminado |
| `actor_repr` | `CharField(150)` | No | No | Snapshot del actor (RN-71) |
| `action` | `CharField(40)` | No | No | Catálogo cerrado, abajo |
| `object_type` | `CharField(60)` | Sí | No | `app_label.ModelName`. **No** es FK a `ContentType` |
| `object_id` | `CharField(40)` | Sí | No | PK o `public_id` del objeto, como texto |
| `object_repr` | `CharField(200)` | Sí | No | Snapshot legible del objeto |
| `outcome` | `CharField(10)` | No | No | Choices: `SUCCESS`, `FAILURE`, `DENIED` |
| `ip_address` | `GenericIPAddressField` | Sí | No | Del `X-Forwarded-For` de confianza |
| `user_agent` | `CharField(255)` | Sí | No | Truncado |
| `request_id` | `UUIDField` | Sí | No | Correlaciona con los logs de aplicación |
| `metadata` | `JSONField` | No | No | Diff filtrado. Por defecto `{}` |

**Catálogo de `action`** (regla 37):

`LOGIN` · `LOGIN_FAILED` · `LOGOUT` · `PASSWORD_CHANGE` · `PASSWORD_RESET_REQUEST` ·
`PASSWORD_RESET_COMPLETE` · `EMAIL_VERIFIED` · `USER_CREATE` · `USER_DEACTIVATE` ·
`ACTIVATION_CODE_ISSUE` · `ACTIVATION_CODE_REDEEM` · `ACTIVATION_CODE_FAILED` ·
`ACTIVATION_CODE_REVOKE` ·
`ROLE_CHANGE` · `PERMISSION_CHANGE` · `PERMISSION_DENIED` ·
`DEPARTMENT_CREATE` · `DEPARTMENT_UPDATE` · `DEPARTMENT_DEACTIVATE` ·
`POSITION_CREATE` · `POSITION_UPDATE` · `POSITION_DEACTIVATE` ·
`JOB_GRADE_CREATE` · `JOB_GRADE_UPDATE` ·
`EMPLOYEE_CREATE` · `EMPLOYEE_UPDATE` · `EMPLOYEE_VIEW_SENSITIVE` ·
`CONTRACT_CREATE` · `CONTRACT_UPDATE` · `CONTRACT_TERMINATE` · `SALARY_CHANGE` ·
`ASSIGNMENT_CREATE` · `ASSIGNMENT_END` ·
`LEAVE_SUBMIT` · `LEAVE_APPROVE` · `LEAVE_REJECT` · `LEAVE_CANCEL` ·
`ATTENDANCE_ADJUST` ·
`DOCUMENT_UPLOAD` · `DOCUMENT_DOWNLOAD` · `DOCUMENT_DELETE` ·
`PAYROLL_RUN_EXECUTE` · `PAYROLL_RUN_APPROVE` · `EXPORT_DATA`

**Reglas de la entidad:**

- **RN-70 append-only.** El modelo sobrescribe `save()` para rechazar
  actualizaciones y no expone `delete()`. Además, los permisos
  `change_auditevent` y `delete_auditevent` **no se otorgan a ningún grupo**,
  incluido `HR_ADMIN`; solo un superusuario por consola podría eludirlo, y esa
  acción queda en los logs del sistema operativo.
- **RN-72 sin secretos.** Un filtro de campos (`password`, `token`, `csrf`,
  `session`, `secret`, `authorization`, `api_key`) depura `metadata` antes de
  persistir. Este filtro tiene test propio.
- El PII en `object_repr` se limita a identificadores no sensibles (código de
  empleado, nunca el DPI).
- **Retención:** indefinida en esta fase. Con volumen alto, se particionará por
  fecha tras migrar a PostgreSQL.
- **Índices:** `occurred_at`, `(actor_id, occurred_at)`,
  `(object_type, object_id)`, `(action, occurred_at)`

---

## G.18 Entidades de fases posteriores

Documentadas a nivel de esquema en [B. Modelo relacional](02-modelo-relacional.md)
y [F. ERD](05-erd.md). Su diccionario completo se redactará al abrir cada fase.

| Fase | Entidades | Estado del diseño |
|---|---|---|
| 5 | `WorkSchedule`, `WorkScheduleDay`, `ScheduleAssignment`, `AttendanceEntry`, `AttendanceIncident` | Esquema definido; falta afinar reglas de cálculo de horas extra y tolerancias |
| 6 | `LeaveType`, `LeaveEntitlement`, `LeaveRequest`, `LeaveRequestTransition`, `LeaveLedgerEntry` | Esquema definido; falta parametrizar el devengo por antigüedad |
| 7 | `DocumentType`, `EmployeeDocument` | **Implementadas** (Fase 7). Sigue pendiente la política de retención por tipo: `retention_years` se captura y no se aplica |
| 8 | `PayrollPeriod`, `PayrollRun`, `PayrollConcept`, `Payslip`, `PayslipLine` | **Anteproyecto.** Requiere análisis de dominio propio antes de implementar |

---

## G.19 Clasificación de datos

Determina quién puede ver qué y qué se puede registrar en logs.

| Nivel | Entidades / campos | Regla de acceso | ¿En logs? |
|---|---|---|---|
| **Público interno** | `Department.name`, `Position.title`, `Employee.employee_code` | Cualquier usuario autenticado | Sí |
| **Personal (PII)** | `Person.*`, `ContactMethod`, `Address`, `EmergencyContact` | RRHH, el propio empleado; MANAGER solo datos de contacto laboral | Solo el ID |
| **PII sensible** | `IdentityDocument.number`, `Person.birth_date`, `Person.marital_status` | RRHH y el propio empleado. Enmascarado en listados | **Nunca** |
| **Confidencial** | `ContractSalary.*`, `JobGrade.min/max_salary`, `Payslip.*` | RRHH y el propio empleado. **Nunca** MANAGER por defecto | **Nunca** |
| **Restringido** | `User.password`, `AccountActivationCode.code_hash`, tokens, sesiones | Nadie. Solo la maquinaria de Django | **Nunca** |
| **Auditoría** | `AuditEvent.*` | AUDITOR (lectura) y SUPERADMIN | Sí, es su propósito |
