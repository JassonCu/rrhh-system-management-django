# B. Modelo relacional

Notación empleada:

- `Relación(**PK**, _FK_, atributo)` — **negrita** = clave primaria, _cursiva_ = clave foránea.
- `CK` = clave candidata (identifica unívocamente una tupla, además de la PK).
- `UQ` = restricción de unicidad; `CH` = restricción de verificación (check).
- `UQ*` = unicidad **parcial** (con condición), implementable en SQLite y
  PostgreSQL mediante `UniqueConstraint(condition=Q(...))` de Django.

El detalle de tipos, longitudes y nulabilidad está en el
[Diccionario de datos](06-diccionario-de-datos.md). Las políticas de borrado y
los índices están en [Integridad e índices](07-integridad-e-indices.md).

**Decisión general de clave primaria:** todas las relaciones usan una **clave
sustituta** `BigAutoField`. Ninguna clave primaria contiene información personal
(regla 21): DPI, NIT, correo o teléfono nunca son PK, porque son mutables,
sensibles y quedarían expuestos en URLs y FKs. Las claves naturales existen, se
documentan como CK y se protegen con `UniqueConstraint`.

**Identificador público:** las entidades expuestas en URLs (`Employee`,
`EmploymentContract`, `LeaveRequest`, `EmployeeDocument`) llevan además un campo
`public_id` (UUIDv4, único, indexado) usado en el enrutamiento. Esto evita
enumeración trivial, pero **no sustituye la autorización** (regla 22): cada vista
verifica el permiso sobre el objeto aunque el identificador sea impredecible.

---

## B.1 Contexto `core`

### `Company` — entidad legal empleadora

`Company(**id**, code, legal_name, trade_name, tax_id, country, is_active, created_at, updated_at)`

- **Propósito:** representa la persona jurídica con la que se firman los contratos.
- **CK:** `{id}`, `{code}`, `{tax_id}`
- **UQ:** `code`, `tax_id`
- **CH:** `country` ∈ ISO-3166-1 alfa-2

### `Holiday` — feriado oficial

`Holiday(**id**, _company_id_, date, name, is_mandatory)`

- **Propósito:** insumo para el cálculo de días hábiles en `leave` y `attendance`.
- **CK:** `{id}`, `{company_id, date}`
- **UQ:** `(company_id, date)`
- **Nota:** se modela por empresa porque los asuetos locales pueden diferir entre
  sedes. Con una sola empresa, la restricción degenera en "una fecha, un feriado".

---

## B.2 Contexto `accounts`

### `User` — credencial de acceso

`User(**id**, email, password, is_active, is_staff, is_superuser, last_login, date_joined, must_change_password, language, created_at, updated_at)`

- **Propósito:** autenticación. **No** contiene datos de RRHH.
- **CK:** `{id}`, `{email}`
- **UQ:** `email` (case-insensitive; normalizado a minúsculas en el modelo)
- **Decisión:** `AbstractBaseUser` + `PermissionsMixin` con `USERNAME_FIELD = "email"`.
  Se descarta `username` por ser un dato sin valor de dominio. Se crea desde la
  Fase 1 aunque no se use plenamente hasta la Fase 2: sustituir el modelo de
  usuario después de la primera migración es notoriamente costoso.
- **Nota:** nombres y apellidos **no** viven aquí (viven en `Person`). `User` no
  duplica identidad civil; si el usuario no es empleado, se muestra su correo.

### `AccountActivationCode` — código de activación de un solo uso (Fase 6)

`AccountActivationCode(**id**, _user_id_, code_hash, status, expires_at, resolved_at, _created_by_id_, created_at)`

- **Propósito:** permitir que RRHH dé de alta a personal **sin correo
  corporativo** entregando en mano un token revocable, en lugar de una
  contraseña ([ADR-004](../decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md)).
- **CK:** `{id}`, `{code_hash}`
- **UQ:** `code_hash`
- **UQ\*:** `(user_id)` donde `status = 'PENDING'` — un solo código pendiente por
  usuario; emitir uno nuevo revoca el anterior
- **CH:** `status` ∈ {PENDING, REDEEMED, REVOKED}; `expires_at > created_at`;
  `(status = 'PENDING') = (resolved_at IS NULL)`
- **Nota sobre el estado `EXPIRED`:** **no existe** como valor de `status`. La
  caducidad es derivable de `expires_at` y convertirla en estado obligaría a un
  proceso periódico que cambie filas — trabajo y complejidad para representar
  algo que una comparación de fechas ya responde.
- **Nota de seguridad:** solo se almacena `HMAC-SHA256(código, SECRET_KEY)`. El
  valor en claro se muestra una única vez al emitirlo y no es recuperable, ni por
  RRHH ni por un administrador de base de datos.

Los roles se implementan con `auth.Group` y `auth.Permission` nativos de Django
(ver [Autorización](../security/10-autorizacion.md)); no se crea una tabla de
roles propia.

---

## B.3 Contexto `employees`

### `Person` — identidad civil

`Person(**id**, first_name, middle_name, last_name, second_last_name, birth_date, gender, marital_status, nationality, created_at, updated_at)`

- **CK:** `{id}`. **No existe clave natural fiable**: el nombre no es único y la
  fecha de nacimiento tampoco lo hace único. La identificación natural la aporta
  `IdentityDocument`.
- **CH:** `birth_date < CURRENT_DATE`; `gender`, `marital_status` ∈ choices.
- **Nota:** se usan cuatro campos de nombre por la convención hispanoamericana
  (dos apellidos). `full_name` **no se almacena**: es derivable y almacenarlo
  produciría anomalías de actualización.

### `IdentityDocument` — documento de identificación

`IdentityDocument(**id**, _person_id_, document_type, number, issuing_country, issued_on, expires_on, is_primary)`

- **Propósito:** DPI/CUI, NIT, número de afiliación IGSS, pasaporte, licencia.
- **CK:** `{id}`, `{document_type, number, issuing_country}`
- **UQ:** `(document_type, number, issuing_country)` — RN-02
- **UQ\*:** `(person_id, document_type, issuing_country)` donde `expires_on IS NULL OR expires_on >= CURRENT_DATE` — RN-03
- **CH:** `issued_on <= expires_on`; `number` no vacío tras normalizar.
- **Nota:** los formatos por tipo (CUI de 13 dígitos con verificador, NIT con
  módulo 11) se validan con validadores del dominio, no con `CheckConstraint`,
  porque dependen del país y evolucionan.

### `ContactMethod` — teléfono o correo personal

`ContactMethod(**id**, _person_id_, contact_type, value, is_primary, notes)`

- **CK:** `{id}`, `{person_id, contact_type, value}`
- **UQ:** `(person_id, contact_type, value)`
- **UQ\*:** `(person_id, contact_type)` donde `is_primary = TRUE` — RN-05
- **CH:** `contact_type` ∈ {MOBILE, LANDLINE, PERSONAL_EMAIL, WORK_EMAIL}
- **Justificación 1NF:** esta relación existe precisamente para prohibir
  `phones = "5551111,5552222"`. Ver [Normalización §D.3](04-normalizacion.md).

### `Address` — dirección

`Address(**id**, _person_id_, address_type, line1, line2, locality, region, postal_code, country, is_primary)`

- **CK:** `{id}`
- **UQ\*:** `(person_id)` donde `is_primary = TRUE` — RN-06
- **CH:** `address_type` ∈ {HOME, MAILING}; `country` ∈ ISO-3166-1 alfa-2
- **Nota:** `region`/`locality` son texto libre por decisión explícita (A.6). Al no
  existir catálogo geográfico, no hay dependencia funcional oculta
  `postal_code → locality` que resolver; si se introduce el catálogo, se migra a
  FKs.

### `Employee` — identidad laboral

`Employee(**id**, public_id, _person_id_, _user_id_, employee_code, hire_date, employment_status, termination_date, created_at, updated_at)`

- **CK:** `{id}`, `{public_id}`, `{employee_code}`, `{person_id}`
- **UQ:** `public_id`, `employee_code`, `person_id` (1:1), `user_id` (1:0..1, nulo permitido)
- **CH:** `employment_status` ∈ {ACTIVE, ON_LEAVE, SUSPENDED, TERMINATED};
  `termination_date IS NULL OR termination_date >= hire_date` (RN-17);
  `employment_status = 'TERMINATED'` ⟺ `termination_date IS NOT NULL`
- **Nota sobre `employment_status`:** es estado corriente derivable de los
  contratos. Se conserva como columna por razones de consulta y por ser el punto
  de anclaje de las transiciones de ciclo de vida; la coherencia con los
  contratos es una **invariante de servicio** (RN-18) verificada por tests, no
  una dependencia transitiva. Ver [§D.7](04-normalizacion.md#d7-redundancia-justificada).

### `EmergencyContact` — contacto de emergencia

`EmergencyContact(**id**, _employee_id_, full_name, relationship, phone, alternate_phone, priority)`

- **CK:** `{id}`, `{employee_id, priority}`
- **UQ:** `(employee_id, priority)`
- **CH:** `priority >= 1`; `relationship` ∈ choices
- **Nota:** `full_name` aquí **no** viola 3NF: el contacto es una persona externa
  que no existe como `Person` en el sistema; el atributo depende solo de la PK.

---

## B.4 Contexto `departments`

### `Department` — nodo del organigrama

`Department(**id**, _company_id_, _parent_id_, code, name, cost_center, is_active, created_at, updated_at)`

- **CK:** `{id}`, `{company_id, code}`
- **UQ:** `(company_id, code)` — RN-30
- **CH:** `parent_id <> id` (autorreferencia directa). La aciclicidad completa
  (RN-31) **no es expresable** como `CheckConstraint` en SQLite ni en PostgreSQL
  sin trigger recursivo: se valida en el servicio y se cubre con tests.
- **Nota:** jerarquía por lista de adyacencia (`parent_id`). Se descartan
  *materialized path*, *nested set* y `django-mptt` por YAGNI: la profundidad
  esperada es ≤ 5 y las consultas de subárbol se resuelven con una CTE recursiva
  o con una expansión iterativa acotada.

### `DepartmentHeadship` — jefatura vigente/histórica

`DepartmentHeadship(**id**, _department_id_, _employee_id_, start_date, end_date, appointment_note)`

- **CK:** `{id}`, `{department_id, start_date}`
- **UQ:** `(department_id, start_date)`
- **UQ\*:** `(department_id)` donde `end_date IS NULL` — RN-32
- **CH:** `start_date <= end_date` cuando `end_date` no es nulo
- **No traslape** de períodos por departamento: validado en servicio + test
  (no expresable como constraint declarativo portable).

---

## B.5 Contexto `positions`

### `JobGrade` — banda salarial

`JobGrade(**id**, code, name, level, min_salary, max_salary, currency, is_active)`

- **CK:** `{id}`, `{code}`
- **UQ:** `code`
- **CH:** `min_salary > 0`; `min_salary <= max_salary` (RN-34); `level >= 1`
- **Justificación 3NF:** el rango salarial depende del **grado**, no del puesto.
  Si `min_salary`/`max_salary` viviesen en `Position`, un cambio de banda
  obligaría a actualizar N puestos (anomalía de actualización) y permitiría
  valores contradictorios entre puestos del mismo grado.

### `Position` — puesto de trabajo (catálogo)

`Position(**id**, _department_id_, _job_grade_id_, code, title, description, is_active, created_at, updated_at)`

- **CK:** `{id}`, `{code}`, `{department_id, title}`
- **UQ:** `code`; `(department_id, title)` — RN-35
- **Decisión clave ([ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md)):**
  el puesto **pertenece a un departamento**. El negocio confirmó que ningún
  título es transversal y que el perfil se define por área, de modo que la
  dependencia funcional `position_id → department_id` **se cumple**. La
  consecuencia directa es que `Assignment` **no** puede almacenar el
  departamento: sería transitivo. Ver
  [§D.5](04-normalizacion.md#d5-tercera-forma-normal-3nf).
- **Nota:** `code` es único en toda la organización; el título solo tiene que
  serlo dentro de su departamento.

---

## B.6 Contexto `contracts`

### `EmploymentContract` — relación laboral

`EmploymentContract(**id**, public_id, _employee_id_, _company_id_, contract_type, start_date, end_date, probation_end_date, status, termination_reason, termination_date, signed_on, notes, created_at, updated_at)`

- **CK:** `{id}`, `{public_id}`
- **UQ:** `public_id`
- **UQ\*:** `(employee_id)` donde `status IN ('ACTIVE', 'SUSPENDED')` — RN-13 (**la regla de
  negocio más importante del sistema, garantizada por la base de datos**)
- **CH:**
  - `end_date IS NULL OR start_date <= end_date` (RN-10)
  - `contract_type <> 'FIXED_TERM' OR end_date IS NOT NULL` (RN-12)
  - `probation_end_date IS NULL OR probation_end_date >= start_date` (RN-15)
  - `status <> 'TERMINATED' OR (termination_date IS NOT NULL AND termination_reason IS NOT NULL)` (RN-16)
  - `contract_type` ∈ {INDEFINITE, FIXED_TERM, TEMPORARY, INTERNSHIP}
  - `status` ∈ {DRAFT, ACTIVE, SUSPENDED, TERMINATED, EXPIRED}
- **No traslape** entre contratos del mismo empleado (RN-14): en servicio + test.
  El `UQ*` de contrato activo cubre el caso crítico de forma declarativa.

### `ContractSalary` — historial salarial

`ContractSalary(**id**, _contract_id_, amount, currency, pay_frequency, effective_from, effective_to, change_reason, justification, _created_by_id_, created_at)`

> `justification` es obligatoria por servicio cuando el importe cae fuera de la
> banda del puesto principal vigente (RN-23). Depende de la clave completa: es la
> razón de **ese** período salarial, no del contrato.

- **CK:** `{id}`, `{contract_id, effective_from}`
- **UQ:** `(contract_id, effective_from)`
- **UQ\*:** `(contract_id)` donde `effective_to IS NULL` — RN-20
- **CH:** `amount > 0`; `effective_to IS NULL OR effective_from <= effective_to`;
  `pay_frequency` ∈ {MONTHLY, BIWEEKLY, WEEKLY}; `currency` ∈ ISO-4217
- **Nota:** la continuidad sin huecos (RN-21) se mantiene en el servicio, que
  cierra el registro anterior (`effective_to = nuevo_from - 1 día`) dentro de la
  misma transacción en que abre el nuevo.

### `Assignment` — asignación puesto + departamento

`Assignment(**id**, _contract_id_, _position_id_, start_date, end_date, is_primary, fte, assignment_reason, created_at)`

- **CK:** `{id}`, `{contract_id, position_id, start_date}`
- **UQ:** `(contract_id, position_id, start_date)`
- **UQ\*:** `(contract_id)` donde `end_date IS NULL AND is_primary = TRUE` — RN-24
- **CH:** `end_date IS NULL OR start_date <= end_date`; `0 < fte <= 1.00`
- **Esta relación no contiene ninguna referencia redundante**, y las dos que
  faltan lo hacen por el mismo motivo:
  - **Sin `employee_id`:** `contract_id → employee_id`, luego sería transitivo.
    "Asignaciones del empleado X" se resuelve con
    `Assignment.objects.filter(contract__employee=x)`.
  - **Sin `department_id`:** `position_id → department_id` (ADR-011), luego
    también sería transitivo. El departamento se obtiene por
    `assignment.position.department`.

  Ver [§D.5](04-normalizacion.md#d5-tercera-forma-normal-3nf).
- **Trade-off aceptado:** RN-25 (suma de FTE ≤ 1) y RN-26 (contención de fechas)
  requieren consultar el contrato y, por tanto, no son constraints declarativos;
  se validan en `services.py` bajo transacción con `select_for_update` y se
  cubren con tests explícitos.

---

## B.7 Contexto `attendance` (Fase 5)

### `WorkSchedule` — jornada pactada (catálogo)

`WorkSchedule(**id**, code, name, weekly_hours, grace_minutes, is_active)`

> **`grace_minutes` se añadió en la Fase 5** ([ADR-021](../decisions/ADR-021-reglas-de-asistencia.md)):
> la tolerancia antes de marcar tardanza es una regla **por jornada**, no una
> constante del sistema. `CH: grace_minutes <= 120`.

- **CK:** `{id}`, `{code}`; **UQ:** `code`; **CH:** `0 < weekly_hours <= 168`

### `WorkScheduleDay` — día de la jornada

`WorkScheduleDay(**id**, _work_schedule_id_, weekday, start_time, end_time, break_minutes)`

- **CK:** `{id}`, `{work_schedule_id, weekday}`; **UQ:** `(work_schedule_id, weekday)`
- **CH:** `0 <= weekday <= 6`; `start_time < end_time`; `break_minutes >= 0`
- **Justificación 1NF:** evita columnas repetidas (`monday_start`, `tuesday_start`, …),
  que son un grupo repetitivo disfrazado.

### `ScheduleAssignment` — jornada vigente de un contrato

`ScheduleAssignment(**id**, _contract_id_, _work_schedule_id_, start_date, end_date)`

- **CK:** `{id}`, `{contract_id, start_date}`; **UQ:** `(contract_id, start_date)`
- **UQ\*:** `(contract_id)` donde `end_date IS NULL`
- **Justificación:** la jornada cambia durante la vida del contrato; una columna
  `work_schedule_id` en `EmploymentContract` perdería el historial.

### `AttendanceEntry` — segmento de marcaje

`AttendanceEntry(**id**, _employee_id_, work_date, check_in_at, check_out_at, source, _registered_by_id_, note, created_at)`

- **CK:** `{id}`, `{employee_id, work_date, check_in_at}`
- **UQ:** `(employee_id, work_date, check_in_at)`
- **CH:** `check_out_at IS NULL OR check_in_at < check_out_at` (RN-50);
  `source` ∈ {SELF, SUPERVISOR, HR, DEVICE, IMPORT}
- **Nota:** se admiten varios segmentos por día (jornada partida). El total diario
  **no se almacena**: se calcula con agregación en un selector. Si el volumen lo
  exige, se materializará en una tabla `AttendanceDay` tras medir.

### `AttendanceIncident` — incidencia

`AttendanceIncident(**id**, _employee_id_, work_date, incident_type, minutes, status, justification, _resolved_by_id_, resolved_at)`

- **CK:** `{id}`, `{employee_id, work_date, incident_type}`
- **UQ:** `(employee_id, work_date, incident_type)`
- **CH:** `minutes >= 0`; `incident_type` ∈ {LATE, EARLY_LEAVE, ABSENCE, OVERTIME, MISSING_PUNCH};
  `status` ∈ {OPEN, JUSTIFIED, REJECTED}

---

## B.8 Contexto `leave` (Fase 6)

> **Implementado en la Fase 6.** Diferencias con este diseño, todas deliberadas:
>
> - `requested_days` se llama `working_days`: el nombre dice que son **hábiles**.
> - `LeaveType.is_sensitive` y `LeaveType.max_backdating_days` son nuevos
>   ([ADR-022](../decisions/ADR-022-reglas-de-ausencias.md) §3 y §5).
> - `LeaveAccrualTier(leave_type, min_years_of_service, annual_days)` es nueva:
>   días por antigüedad, con `UQ(leave_type, min_years_of_service)` y
>   `min_years_of_service >= 1` (ADR-022 §6).
> - `LeaveRequest` guarda la decisión (`decided_by`, `decided_at`,
>   `decision_note`) con una restricción de coherencia; `submitted_at` no se
>   almacena porque la transición ya lo dice.
> - La transición de creación tiene `from_status` vacío; `actor_repr` no existe
>   porque el actor es `SET_NULL` y la bitácora guarda el snapshot.
> - El asiento no tiene `effective_date` (lo da `created_at`, y el período lo da
>   el derecho) ni el tipo `EXPIRY`, que ninguna política exige hoy.

### `LeaveType` — tipo de ausencia (catálogo)

`LeaveType(**id**, code, name, is_paid, requires_approval, requires_document, allows_negative_balance, default_annual_days, min_notice_days, is_active)`

- **CK:** `{id}`, `{code}`; **UQ:** `code`
- **CH:** `default_annual_days >= 0`; `min_notice_days >= 0`

### `LeaveEntitlement` — derecho por período

`LeaveEntitlement(**id**, _employee_id_, _leave_type_id_, period_start, period_end, granted_days, source, created_at)`

- **CK:** `{id}`, `{employee_id, leave_type_id, period_start}`
- **UQ:** `(employee_id, leave_type_id, period_start)`
- **CH:** `period_start < period_end`; `granted_days >= 0`;
  `source` ∈ {ACCRUAL, MANUAL, CARRYOVER}

### `LeaveRequest` — solicitud

`LeaveRequest(**id**, public_id, _employee_id_, _leave_type_id_, start_date, end_date, requested_days, status, reason, submitted_at, created_at, updated_at)`

- **CK:** `{id}`, `{public_id}`; **UQ:** `public_id`
- **CH:** `start_date <= end_date` (RN-40); `requested_days > 0`;
  `status` ∈ {DRAFT, SUBMITTED, APPROVED, REJECTED, CANCELLED}
- **No traslape** (RN-41) con otras solicitudes `SUBMITTED`/`APPROVED` del mismo
  empleado: servicio + test.
- **Nota:** `requested_days` **se almacena** aunque parezca derivable de las
  fechas. No lo es: depende de la jornada y del calendario de feriados *vigentes
  al momento de solicitar*. Es un valor congelado, no una duplicación (ver §D.7).

### `LeaveRequestTransition` — historial de decisiones

`LeaveRequestTransition(**id**, _leave_request_id_, from_status, to_status, _actor_id_, actor_repr, occurred_at, note)`

- **CK:** `{id}`; **CH:** `from_status <> to_status`
- **Append-only.** El aprobador no puede ser el solicitante (RN-44): servicio + test.

### `LeaveLedgerEntry` — asiento de días

`LeaveLedgerEntry(**id**, _employee_id_, _leave_type_id_, _leave_request_id_, entry_type, days, effective_date, note, _created_by_id_, created_at)`

- **CK:** `{id}`
- **CH:** `entry_type` ∈ {ACCRUAL, CONSUMPTION, ADJUSTMENT, EXPIRY, REVERSAL};
  `days <> 0`; signo coherente con `entry_type` (positivo para ACCRUAL, negativo
  para CONSUMPTION/EXPIRY)
- **Append-only.** El saldo es `SUM(days)` filtrado por empleado, tipo y período.

---

## B.9 Contexto `documents` (Fase 7)

> **Implementado en la Fase 7.** Diferencias con este diseño, todas deliberadas:
>
> - `allowed_extensions` es un `CharField` separado por comas, la alternativa que
>   el propio diseño admitía: un `ArrayField` ataría el proyecto a PostgreSQL
>   (ADR-003).
> - `DocumentType` gana `employee_can_upload`, para la celda «P (tipos
>   permitidos)» de la matriz §J.2.
> - `EmployeeDocument` gana `is_active` y `archived_reason`: un documento se
>   archiva, no se borra ([ADR-023](../decisions/ADR-023-expediente-documental.md)).
> - El índice único por checksum es **parcial** (`is_active = TRUE`): archivar
>   libera el checksum para volver a subir el archivo corregido.
> - `stored_path` es un `FileField`; `uploaded_at` no se duplica porque
>   `TimeStampedModel` ya aporta `created_at`.

### `DocumentType` — tipo de documento (catálogo)

`DocumentType(**id**, code, name, is_sensitive, requires_expiry, retention_years, allowed_extensions, max_size_mb, is_active)`

- **CK:** `{id}`, `{code}`; **UQ:** `code`
- **CH:** `retention_years >= 0`; `0 < max_size_mb <= 25`
- **Nota:** `allowed_extensions` es una lista corta y cerrada de configuración
  (`["pdf","png","jpg"]`). Es el **único** uso de un campo de lista en el diseño
  y se justifica porque no es una relación del dominio (no se consulta ni se une),
  sino una política de validación. Alternativa aceptable: `CharField` con valores
  separados por coma parseados por el validador. **No** se usa JSON para
  representar relaciones (regla 7).

### `EmployeeDocument` — documento del expediente

`EmployeeDocument(**id**, public_id, _employee_id_, _document_type_id_, title, stored_path, original_filename, content_type, size_bytes, checksum_sha256, issued_on, expires_on, _uploaded_by_id_, uploaded_at, is_active)`

- **CK:** `{id}`, `{public_id}`; **UQ:** `public_id`
- **UQ\*:** `(employee_id, document_type_id, checksum_sha256)` donde `is_active = TRUE`
  (evita subir dos veces el mismo archivo)
- **CH:** `size_bytes > 0`; `expires_on IS NULL OR issued_on IS NULL OR issued_on <= expires_on`;
  `length(checksum_sha256) = 64`
- **Nota de seguridad:** `stored_path` es un nombre generado (UUID + extensión
  validada) bajo un directorio privado; **nunca** el nombre subido por el usuario.
  `original_filename` se guarda solo para mostrarlo, escapado. Ver
  [Seguridad §K.6](../security/11-seguridad.md).

---

## B.10 Contexto `payroll` (Fase 8 — solo forma general)

> Estas relaciones se presentan como **anteproyecto**. La nómina exige un análisis
> propio (períodos, conceptos, bases de cálculo, prestaciones de ley, IGSS, ISR)
> que se realizará al inicio de la Fase 8. **No se implementarán con este nivel de
> detalle.**

- `PayrollPeriod(**id**, _company_id_, code, period_type, start_date, end_date, status)` — UQ `(company_id, code)`
- `PayrollRun(**id**, _period_id_, run_number, status, executed_at, _executed_by_id_, locked_at)` — UQ `(period_id, run_number)`
- `PayrollConcept(**id**, code, name, nature, calculation_basis, is_active)` — UQ `code`
- `Payslip(**id**, public_id, _run_id_, _employee_id_, employee_code_snapshot, full_name_snapshot, position_title_snapshot, department_name_snapshot, base_salary_snapshot, gross_total, deduction_total, net_total)` — UQ `(run_id, employee_id)`
- `PayslipLine(**id**, _payslip_id_, _concept_id_, quantity, rate, amount, sequence)` — UQ `(payslip_id, concept_id, sequence)`

Los campos `*_snapshot` son **redundancia deliberada** documentada en
[§D.7](04-normalizacion.md#d7-redundancia-justificada).

---

## B.11 Contexto `audit`

### `AuditEvent` — evento auditable

`AuditEvent(**id**, occurred_at, _actor_id_, actor_repr, action, object_type, object_id, object_repr, outcome, ip_address, user_agent, request_id, metadata)`

- **CK:** `{id}`
- **CH:** `outcome` ∈ {SUCCESS, FAILURE, DENIED}; `action` ∈ catálogo de acciones
- **Sin UQ:** los eventos se repiten por naturaleza.
- **`actor_repr` y `object_repr` son snapshots deliberados** (RN-71): el evento
  debe seguir siendo legible aunque el actor o el objeto se hayan eliminado. No
  es una violación de 3NF sino un registro de hecho histórico (§D.7).
- **`metadata` es `JSONField`:** este es el caso legítimo de JSON del sistema
  (regla 7) — el diff de campos modificados es genuinamente semiestructurado,
  varía por tipo de objeto, no se consulta relacionalmente y no representa una
  relación del dominio. Se filtra antes de guardar para excluir campos sensibles
  (RN-72).
- **`object_type`/`object_id` son punteros débiles** (texto `"employees.Employee"`
  + entero), **no** una `GenericForeignKey`. Motivo: una FK real a `ContentType`
  no impide que el objeto desaparezca, complica la migración a PostgreSQL con
  particionado y acopla la auditoría al ciclo de vida del dato auditado. Se acepta
  la ausencia de integridad referencial aquí de forma consciente: la auditoría
  registra hechos pasados, no referencias vivas.
