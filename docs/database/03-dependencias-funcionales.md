# C. Dependencias funcionales

Notación: `X → Y` significa que el conjunto de atributos `X` determina
funcionalmente a `Y`. Se listan únicamente las dependencias **no triviales y
relevantes para el diseño**; se omite la dependencia obvia `PK → resto` cuando no
aporta información (aunque se indica para dejar constancia de que existe y de que
es la única, que es precisamente el criterio de BCNF).

---

## C.1 Convenciones sobre claves

| Tipo de clave | Uso en este diseño |
|---|---|
| **Clave sustituta** (`id`, `BigAutoField`) | PK de todas las relaciones. Estable, opaca, no sensible |
| **Clave natural** | Existe en la mayoría de catálogos (`code`, `employee_code`, documento de identidad). Se declara como `UniqueConstraint`, nunca como PK |
| **Clave candidata** | Todo conjunto minimal que determina la tupla. Se enumeran abajo |
| **Identificador público** (`public_id`, UUIDv4) | Clave candidata adicional, usada solo en URLs |

Consecuencia práctica: al existir clave sustituta, **toda** relación tiene la
dependencia `id → resto`. Eso por sí solo no garantiza 3NF/BCNF; hay que
verificar que ningún **otro** determinante no-candidato exista. Ese es el
análisis que sigue.

---

## C.2 `core`

### `Company`
```
id        → code, legal_name, trade_name, tax_id, country, is_active
code      → id                      (clave natural)
tax_id    → id                      (clave natural)
```
Claves candidatas: `{id}`, `{code}`, `{tax_id}`.
Todo determinante es candidata → **BCNF**.

### `Holiday`
```
id                 → company_id, date, name, is_mandatory
{company_id, date} → id, name, is_mandatory
```
Claves candidatas: `{id}`, `{company_id, date}`. **BCNF**.

---

## C.3 `accounts`

### `User`
```
id    → email, password, is_active, is_staff, is_superuser, last_login, date_joined
email → id, password, ...            (clave natural)
```
Claves candidatas: `{id}`, `{email}`. **BCNF**.

> Nota: si `User` contuviera `first_name`/`last_name` **y** existiera
> `Employee.user_id`, tendríamos el nombre en dos lugares (`User` y `Person`) sin
> una dependencia que decidiera cuál es la fuente de verdad. Esa es la razón
> concreta por la que `User` no lleva nombre.

### `AccountActivationCode`
```
id         → user_id, code_hash, status, expires_at, resolved_at, created_by_id
code_hash  → id, user_id, status, expires_at        (el hash identifica el código)
```
Claves candidatas: `{id}`, `{code_hash}`. Ambos determinantes son candidatas →
**BCNF**.

**No existe** `user_id → code_hash`: un usuario puede acumular varios códigos a
lo largo del tiempo (uno canjeado, otros revocados). La restricción "solo uno
pendiente" es condicional y se expresa con un índice único parcial, no con una
dependencia funcional.

**Ausencia deliberada:** no se almacena el código en claro, luego no existe
`id → code`. Es la única forma de garantizar que un volcado de la base no
contenga tokens utilizables.

---

## C.4 `employees`

### `Person`
```
id → first_name, middle_name, last_name, second_last_name,
     birth_date, gender, marital_status, nationality
```
Clave candidata única: `{id}`. No hay clave natural (nombre + fecha de nacimiento
no es único ni estable). **BCNF trivialmente.**

**Dependencia deliberadamente ausente:** no existe `id → full_name` porque
`full_name` no se almacena; es una función de otros atributos, no un hecho
independiente. Almacenarlo crearía la dependencia
`{first_name, last_name, …} → full_name`, cuyo determinante **no** es clave
candidata: violación de BCNF y fuente directa de anomalías de actualización
(cambiar el apellido dejaría `full_name` obsoleto).

### `IdentityDocument`
```
id                                          → person_id, document_type, number,
                                              issuing_country, issued_on, expires_on, is_primary
{document_type, number, issuing_country}    → id, person_id, issued_on, expires_on
```
Claves candidatas: `{id}`, `{document_type, number, issuing_country}`.
Ambos determinantes son candidatas → **BCNF**.

Obsérvese que **no** existe `person_id → number`: una persona tiene varios
documentos. Si se hubiera modelado como columnas de `Person`
(`Person.dpi`, `Person.nit`, `Person.passport`), la tabla seguiría técnicamente
en 3NF pero sería estructuralmente incorrecta: cada nuevo tipo de documento
exigiría una migración de esquema, y los valores nulos dominarían la tabla.

### `ContactMethod`
```
id                                → person_id, contact_type, value, is_primary
{person_id, contact_type, value}  → id, is_primary
```
Claves candidatas: `{id}`, `{person_id, contact_type, value}`. **BCNF**.

**No existe** `person_id → value`: es exactamente la dependencia multivaluada que
motiva la tabla separada (ver 4NF en [Normalización §D.6](04-normalizacion.md)).

### `Address`
```
id → person_id, address_type, line1, line2, locality, region, postal_code, country, is_primary
```
Clave candidata: `{id}`. **BCNF**.

**Dependencia potencial vigilada:** en un modelo con catálogo geográfico existiría
`postal_code → locality, region` — un determinante que no es clave candidata y,
por tanto, una violación de 3NF. Como aquí `locality`/`region` son texto libre sin
catálogo autoritativo, esa dependencia **no se sostiene como restricción del
dominio** (dos direcciones con el mismo código postal pueden escribir la
localidad de forma distinta sin que el modelo mienta). Si se introduce el catálogo
geográfico, deberá extraerse una relación `PostalCode(**code**, locality, region)`.
Queda registrado como deuda de diseño consciente.

### `Employee`
```
id             → public_id, person_id, user_id, employee_code, hire_date,
                 employment_status, termination_date
employee_code  → id                     (clave natural)
public_id      → id                     (identificador público)
person_id      → id                     (relación 1:1)
```
Claves candidatas: `{id}`, `{employee_code}`, `{public_id}`, `{person_id}`.
Todo determinante es candidata → **BCNF**.

**Ausencias deliberadas** (cada una sería una dependencia transitiva):
- No hay `id → department_name` ni `id → position_title` → viven en `Assignment`.
- No hay `id → current_salary` → vive en `ContractSalary`.
- No hay `id → manager_name` → se deriva de `DepartmentHeadship`.

### `EmergencyContact`
```
id                       → employee_id, full_name, relationship, phone, alternate_phone, priority
{employee_id, priority}  → id, full_name, relationship, phone
```
Claves candidatas: `{id}`, `{employee_id, priority}`. **BCNF**.

---

## C.5 `departments` y `positions`

### `Department`
```
id                    → company_id, parent_id, code, name, cost_center, is_active
{company_id, code}    → id, name, parent_id, cost_center
```
Claves candidatas: `{id}`, `{company_id, code}`. **BCNF**.

**Ausencia deliberada:** no existe `id → manager_employee_id`. La jefatura es
temporal; la dependencia real es
`{department_id, start_date} → employee_id` en `DepartmentHeadship`.

### `DepartmentHeadship`
```
id                             → department_id, employee_id, start_date, end_date
{department_id, start_date}    → id, employee_id, end_date
```
Claves candidatas: `{id}`, `{department_id, start_date}`. **BCNF**.

### `JobGrade`
```
id    → code, name, level, min_salary, max_salary, currency, is_active
code  → id, min_salary, max_salary
```
Claves candidatas: `{id}`, `{code}`. **BCNF**.

### `Position`
```
id                        → department_id, job_grade_id, code, title, description, is_active
code                      → id, department_id, title, job_grade_id
{department_id, title}    → id, code, job_grade_id
```
Claves candidatas: `{id}`, `{code}`, `{department_id, title}`.
Todo determinante es candidata → **BCNF**.

**Dependencia que sí existe (ADR-011):** `position_id → department_id`. El
negocio confirmó que ningún título de puesto es transversal y que el perfil se
define por área. Esta DF es la que obliga a que `Assignment` **no** almacene el
departamento.

**Dependencia transitiva evitada:** existe la cadena
`position_id → job_grade_id → min_salary, max_salary`. Almacenar `min_salary` en
`Position` crearía la dependencia transitiva `position_id → min_salary`, que es la
violación de 3NF de manual. Por eso el rango salarial vive **solo** en `JobGrade`.

---

## C.6 `contracts`

### `EmploymentContract`
```
id         → public_id, employee_id, company_id, contract_type, start_date, end_date,
             probation_end_date, status, termination_reason, termination_date, signed_on
public_id  → id
```
Claves candidatas: `{id}`, `{public_id}`. **BCNF**.

**Restricción adicional (no es una DF, es una dependencia con condición):**
`employee_id → id` se cumple **solo** dentro del subconjunto `status = 'ACTIVE'`.
Esto es exactamente lo que expresa un índice único parcial, y es la forma correcta
de llevar RN-13 al motor de base de datos en lugar de dejarla en Python.

### `ContractSalary`
```
id                              → contract_id, amount, currency, pay_frequency,
                                  effective_from, effective_to, change_reason
{contract_id, effective_from}   → id, amount, currency, effective_to
```
Claves candidatas: `{id}`, `{contract_id, effective_from}`. **BCNF**.

**Ausencia deliberada:** no existe `contract_id → amount`. Esa dependencia solo se
cumpliría si un contrato tuviera un único salario en toda su vida. Almacenar
`EmploymentContract.salary` haría imposible registrar un aumento sin destruir el
valor anterior — anomalía de actualización con consecuencias legales.

### `Assignment`
```
id                                          → contract_id, position_id, start_date,
                                              end_date, is_primary, fte
{contract_id, position_id, start_date}      → id, end_date, is_primary, fte
```
Claves candidatas: `{id}`, `{contract_id, position_id, start_date}`.
Todo determinante es candidata → **BCNF**.

**Análisis crítico — por qué no hay `employee_id` aquí.** Se cumple
`contract_id → employee_id` (un contrato pertenece a un empleado). Si `Assignment`
almacenara `employee_id`, tendríamos:

```
assignment_id → contract_id → employee_id
```

una **dependencia transitiva** pura, con su anomalía característica: sería posible
insertar una asignación cuyo `employee_id` no coincidiera con el
`contract.employee_id`, y la base de datos no lo impediría. La respuesta correcta
no es un trigger ni una validación en `save()`: es **no almacenar el dato**.

**Análisis crítico — por qué tampoco hay `department_id` aquí.** Es el mismo
razonamiento aplicado a otra cadena. Por ADR-011 se cumple
`position_id → department_id`, luego almacenarlo produciría:

```
assignment_id → position_id → department_id
```

otra dependencia transitiva, con su anomalía característica: sería posible
registrar una asignación cuyo `department_id` no coincidiera con el departamento
del puesto, y la base no lo impediría. El resultado sería una asignación que
pertenece a dos departamentos distintos según por dónde se consulte.

La decisión dependía de un **hecho del dominio**, no del gusto del diseñador: si
existiera aunque fuera un título transversal, la DF no se cumpliría y
`department_id` sería obligatorio aquí. Ver
[Normalización §D.5](04-normalizacion.md#d5-tercera-forma-normal-3nf) y
[ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md).

---

## C.7 `attendance`

### `WorkScheduleDay`
```
id                              → work_schedule_id, weekday, start_time, end_time, break_minutes
{work_schedule_id, weekday}     → id, start_time, end_time, break_minutes
```
Claves candidatas: `{id}`, `{work_schedule_id, weekday}`. **BCNF**.

Es el ejemplo canónico de eliminación de un **grupo repetitivo**: las columnas
`monday_start … sunday_end` en `WorkSchedule` habrían creado siete dependencias
paralelas del mismo tipo, es decir, un atributo multivaluado disfrazado de
columnas (violación de 1NF en su sentido de diseño).

### `AttendanceEntry`
```
id                                        → employee_id, work_date, check_in_at,
                                            check_out_at, source, note
{employee_id, work_date, check_in_at}     → id, check_out_at, source
```
Claves candidatas: `{id}`, `{employee_id, work_date, check_in_at}`. **BCNF**.

**Dependencia derivada no almacenada:** `worked_minutes` es función de
`check_in_at` y `check_out_at`. No se almacena; se calcula. Almacenarlo crearía
`{check_in_at, check_out_at} → worked_minutes`, un determinante no candidato
(violación de BCNF) y una fuente de incoherencia si se corrige un marcaje.

### `AttendanceIncident`
```
{employee_id, work_date, incident_type} → id, minutes, status, justification
```
Claves candidatas: `{id}`, `{employee_id, work_date, incident_type}`. **BCNF**.

---

## C.8 `leave`

### `LeaveType`
```
id   → code, name, is_paid, requires_approval, requires_document,
       default_annual_days, min_notice_days
code → id, name, is_paid, ...
```
Claves candidatas: `{id}`, `{code}`. **BCNF**.

### `LeaveEntitlement`
```
{employee_id, leave_type_id, period_start} → id, period_end, granted_days, source
```
Claves candidatas: `{id}`, `{employee_id, leave_type_id, period_start}`. **BCNF**.

**Ausencia crítica:** **no** existe `{employee_id, leave_type_id} → taken_days` ni
`→ balance`. El saldo no es un atributo: es una agregación sobre `LeaveLedgerEntry`.
Modelarlo como columna crearía un dato cuya verdad depende de que *todo* el código
que aprueba, cancela o ajusta ausencias recuerde actualizarlo — la definición
exacta de una anomalía de actualización.

### `LeaveRequest`
```
id        → public_id, employee_id, leave_type_id, start_date, end_date,
            requested_days, status, reason, submitted_at
public_id → id
```
Claves candidatas: `{id}`, `{public_id}`. **BCNF**.

**Caso sutil — `requested_days`.** A primera vista se cumpliría
`{start_date, end_date} → requested_days`, lo que sería un determinante no
candidato. **No se cumple**: el número de días hábiles depende además de la
jornada del empleado y del calendario de feriados. Formalmente la dependencia sería
`{start_date, end_date, schedule, holiday_calendar} → requested_days`, y como el
calendario puede cambiar con posterioridad, el valor almacenado es un **hecho
congelado en el momento de la solicitud**, no una redundancia. Se documenta como
tal en [§D.7](04-normalizacion.md#d7-redundancia-justificada).

### `LeaveLedgerEntry`
```
id → employee_id, leave_type_id, leave_request_id, entry_type, days, effective_date
```
Clave candidata: `{id}`. **BCNF trivialmente** (tabla de hechos append-only; dos
asientos idénticos son legítimos, p. ej. dos ajustes iguales el mismo día).

---

## C.9 `documents`

### `DocumentType`
```
id   → code, name, is_sensitive, requires_expiry, retention_years,
       allowed_extensions, max_size_mb
code → id, ...
```
Claves candidatas: `{id}`, `{code}`. **BCNF**.

### `EmployeeDocument`
```
id               → public_id, employee_id, document_type_id, title, stored_path,
                   original_filename, content_type, size_bytes, checksum_sha256,
                   issued_on, expires_on, uploaded_by_id, uploaded_at
public_id        → id
stored_path      → id                    (la ruta generada es única por construcción)
checksum_sha256  → ∅                     (NO determina nada: dos empleados pueden
                                          tener copias del mismo formulario)
```
Claves candidatas: `{id}`, `{public_id}`, `{stored_path}`. **BCNF**.

Nótese que `checksum_sha256` **no** es clave: la unicidad solo aplica dentro del
alcance `(employee_id, document_type_id)` y solo para documentos activos.

---

## C.10 `audit`

### `AuditEvent`
```
id → occurred_at, actor_id, actor_repr, action, object_type, object_id,
     object_repr, outcome, ip_address, user_agent, request_id, metadata
```
Clave candidata: `{id}`. **BCNF trivialmente.**

**Análisis obligado — ¿`actor_id → actor_repr` viola 3NF?** Sí lo haría *si*
`actor_repr` fuese el nombre actual del actor. No lo es: es el nombre **en el
instante del evento**. La dependencia real es
`{actor_id, occurred_at} → actor_repr`, y como `occurred_at` forma parte del
hecho registrado, el valor es un dato propio del evento, no una copia del dato
vivo. El mismo razonamiento aplica a `object_repr`. Ver
[§D.7](04-normalizacion.md#d7-redundancia-justificada).

---

## C.11 Resumen

| Relación | Claves candidatas | Máxima FN alcanzada | DF problemática evitada |
|---|---|---|---|
| `Company` | `{id}`, `{code}`, `{tax_id}` | BCNF | — |
| `User` | `{id}`, `{email}` | BCNF | Nombre duplicado con `Person` |
| `AccountActivationCode` | `{id}`, `{code_hash}` | BCNF | Código en claro almacenado |
| `Person` | `{id}` | BCNF | `nombres → full_name` |
| `IdentityDocument` | `{id}`, `{tipo, número, país}` | BCNF (y 4NF) | Columnas por tipo de documento |
| `ContactMethod` | `{id}`, `{person, tipo, valor}` | BCNF (y 4NF) | Lista CSV de teléfonos |
| `Address` | `{id}` | BCNF | `postal_code → locality` (vigilada) |
| `Employee` | `{id}`, `{employee_code}`, `{public_id}`, `{person_id}` | BCNF | `→ department_name`, `→ salary` |
| `Department` | `{id}`, `{company, code}` | BCNF | `→ manager_name` |
| `DepartmentHeadship` | `{id}`, `{department, start_date}` | BCNF | — |
| `JobGrade` | `{id}`, `{code}` | BCNF | — |
| `Position` | `{id}`, `{code}`, `{department, title}` | BCNF | `position → min_salary` (transitiva) |
| `EmploymentContract` | `{id}`, `{public_id}` | BCNF | `→ salary` |
| `ContractSalary` | `{id}`, `{contract, effective_from}` | BCNF | `contract → amount` |
| `Assignment` | `{id}`, `{contract, position, start}` | BCNF (y 4NF) | `→ employee_id` y `→ department_id` (transitivas) |
| `WorkScheduleDay` | `{id}`, `{schedule, weekday}` | BCNF | Grupo repetitivo por día |
| `AttendanceEntry` | `{id}`, `{employee, date, check_in}` | BCNF | `→ worked_minutes` |
| `AttendanceIncident` | `{id}`, `{employee, date, tipo}` | BCNF | — |
| `LeaveType` | `{id}`, `{code}` | BCNF | — |
| `LeaveEntitlement` | `{id}`, `{employee, tipo, period_start}` | BCNF | `→ balance` |
| `LeaveRequest` | `{id}`, `{public_id}` | BCNF | `fechas → días` (no se sostiene) |
| `LeaveLedgerEntry` | `{id}` | BCNF | — |
| `DocumentType` | `{id}`, `{code}` | BCNF | — |
| `EmployeeDocument` | `{id}`, `{public_id}`, `{stored_path}` | BCNF | — |
| `AuditEvent` | `{id}` | BCNF | `actor_id → actor_repr` (snapshot) |
