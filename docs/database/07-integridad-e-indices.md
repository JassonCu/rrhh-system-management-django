# Integridad referencial, constraints e índices

Complementa el [modelo relacional](02-modelo-relacional.md). Responde a las
reglas 15, 18, 19, 23 y 26 del enunciado.

---

## 1. Política de borrado (`on_delete`)

**Regla del proyecto: `PROTECT` es el valor por defecto.** `CASCADE` se usa
únicamente hacia dentro de un agregado cuyo raíz ya está protegido, y `SET_NULL`
solo para referencias a actores donde el hecho debe sobrevivir al actor.
`CASCADE` nunca se escribe "porque Django lo pone por defecto" (regla 15).

| FK | `on_delete` | Justificación |
|---|---|---|
| `Department.company` | `PROTECT` | Borrar la empresa no puede vaciar el organigrama |
| `Department.parent` | `PROTECT` | Borrar un nodo padre huérfanaría el subárbol; primero hay que reubicarlo |
| `Holiday.company` | `PROTECT` | Coherencia con lo anterior |
| `Employee.person` | `PROTECT` | Un empleado sin persona no tiene sentido; la persona no se borra si trabaja aquí |
| `Employee.user` | `SET_NULL` | El empleado existe aunque se le retire el acceso al sistema. **Nunca `CASCADE`**: borrar una cuenta no puede borrar al empleado |
| `AccountActivationCode.user` | `CASCADE` | Parte del agregado `User`. Un usuario no se borra en la práctica; si se borrara, sus códigos deben desaparecer con él y no quedar canjeables |
| `AccountActivationCode.created_by` | `SET_NULL` | El hecho sobrevive a quien lo emitió |
| `IdentityDocument.person` | `CASCADE` | Parte del agregado `Person`. Seguro porque `Person` está protegida por `Employee` |
| `ContactMethod.person` | `CASCADE` | Ídem |
| `Address.person` | `CASCADE` | Ídem |
| `EmergencyContact.employee` | `CASCADE` | Parte del agregado `Employee`, que a su vez nunca se borra |
| `DepartmentHeadship.department` | `PROTECT` | Es historia de gobierno organizacional |
| `DepartmentHeadship.employee` | `PROTECT` | Ídem |
| `Position.department` | `PROTECT` | Borrar un departamento no puede borrar las definiciones de puesto del área ni su historia |
| `Position.job_grade` | `PROTECT` | Un puesto sin banda salarial es un dato inválido |
| `EmploymentContract.employee` | `PROTECT` | **Documento legal.** Regla 15 explícita |
| `EmploymentContract.company` | `PROTECT` | Ídem |
| `ContractSalary.contract` | `PROTECT` | Historial salarial: evidencia para nómina y litigios |
| `ContractSalary.created_by` | `SET_NULL` | El hecho sobrevive a quien lo registró |
| `Assignment.contract` | `PROTECT` | Historia laboral |
| `Assignment.position` | `PROTECT` | Impide borrar un puesto usado alguna vez. Al colgar el departamento del puesto, esto protege también al departamento por transitividad |
| `ScheduleAssignment.contract` | `PROTECT` | — |
| `ScheduleAssignment.work_schedule` | `PROTECT` | — |
| `WorkScheduleDay.work_schedule` | `CASCADE` | Parte del agregado `WorkSchedule`, que sí puede borrarse si nunca se usó (`ScheduleAssignment` lo protege en cuanto se usa) |
| `AttendanceEntry.employee` | `PROTECT` | Base de cálculo de nómina |
| `AttendanceEntry.registered_by` | `SET_NULL` | — |
| `AttendanceIncident.employee` | `PROTECT` | — |
| `AttendanceIncident.resolved_by` | `SET_NULL` | — |
| `LeaveRequest.employee` | `PROTECT` | Evidencia de decisiones laborales |
| `LeaveRequest.leave_type` | `PROTECT` | El tipo se desactiva, no se borra |
| `LeaveRequestTransition.leave_request` | `PROTECT` | Append-only; su padre tampoco se borra |
| `LeaveRequestTransition.actor` | `SET_NULL` | + `actor_repr` conservado |
| `LeaveLedgerEntry.employee` / `.leave_type` | `PROTECT` | Libro contable de días |
| `LeaveLedgerEntry.leave_request` | `PROTECT` | — |
| `LeaveEntitlement.employee` / `.leave_type` | `PROTECT` | — |
| `EmployeeDocument.employee` | `PROTECT` | Expediente legal |
| `EmployeeDocument.document_type` | `PROTECT` | — |
| `EmployeeDocument.uploaded_by` | `SET_NULL` | — |
| `AuditEvent.actor` | `SET_NULL` | **Crítico.** Con `CASCADE`, borrar un usuario borraría su rastro: exactamente lo que buscaría un atacante con acceso al admin |
| `Payslip.run` / `.employee` | `PROTECT` | Documento legal |
| `PayslipLine.payslip` | `CASCADE` | Parte del agregado `Payslip`, protegido a su vez |
| `PayslipLine.concept` | `PROTECT` | — |

### Consecuencia operativa

Con esta política, **casi nada se puede borrar en producción**, que es el
resultado buscado. Las bajas se expresan como estado del dominio
(`employment_status = TERMINATED`, `is_active = False`, `status = CANCELLED`), no
como `DELETE`. Los únicos borrados admitidos son:

| Qué | Condición | Quién | Auditado |
|---|---|---|---|
| `EmploymentContract` en `DRAFT` | Nunca estuvo activo | HR_ADMIN | Sí |
| `LeaveRequest` en `DRAFT` | No enviada | El propio empleado | Sí |
| `EmployeeDocument` | Marcado `is_active = False`; el archivo físico se purga tras el período de retención | HR_ADMIN | Sí |
| Filas de catálogo (`Position`, `LeaveType`, `DocumentType`, `WorkSchedule`) | Sin uso alguno (`PROTECT` lo garantiza) | HR_ADMIN | Sí |

---

## 2. Soft delete: dónde sí y dónde no

No se aplica soft delete de forma indiscriminada (regla 17). No existe un
`SoftDeleteModel` genérico ni un manager que filtre `deleted_at IS NULL` en todo
el proyecto: ese patrón esconde filas, rompe constraints de unicidad y produce
fugas de datos cuando alguien olvida el filtro.

| Entidad | Mecanismo | Motivo |
|---|---|---|
| `Department`, `Position`, `JobGrade`, `LeaveType`, `DocumentType`, `WorkSchedule`, `Company` | `is_active` | Son catálogos referenciados por historia. Desactivar los saca de los formularios sin romper el pasado |
| `Employee` | `employment_status = TERMINATED` | Es un estado del dominio, no un borrado |
| `EmploymentContract`, `LeaveRequest` | `status` | Ídem |
| `EmployeeDocument` | `is_active = False` + purga física diferida | El archivo ocupa espacio y puede tener obligación de eliminación |
| `User` | `is_active = False` | Django ya lo contempla; el `AuthenticationBackend` lo respeta |
| `AuditEvent`, `LeaveLedgerEntry`, `LeaveRequestTransition`, `ContractSalary`, `Assignment`, `AttendanceEntry` | **Ninguno** | Append-only. Una fila incorrecta se corrige con una fila compensatoria, nunca ocultándola |

**Importante:** `is_active = False` **no** es un control de acceso. Un catálogo
inactivo sigue siendo legible por quien tenga permiso; se excluye de los
`ChoiceField` de los formularios, no de la autorización.

---

## 3. Inventario de constraints

### 3.1 `UniqueConstraint` simples

| Entidad | Campos | Regla |
|---|---|---|
| `Company` | `code` / `tax_id` | — |
| `User` | `email` | — |
| `AccountActivationCode` | `code_hash` | — |
| `Employee` | `public_id` / `employee_code` / `person` / `user` | RN-01 |
| `Holiday` | `(company, date)` | — |
| `IdentityDocument` | `(document_type, number, issuing_country)` | RN-02 |
| `ContactMethod` | `(person, contact_type, value)` | — |
| `EmergencyContact` | `(employee, priority)` | — |
| `Department` | `(company, code)` | RN-30 |
| `DepartmentHeadship` | `(department, start_date)` | — |
| `JobGrade` | `code` | — |
| `Position` | `code` / `(department, title)` | RN-35 |
| `EmploymentContract` | `public_id` | — |
| `ContractSalary` | `(contract, effective_from)` | RN-21 |
| `Assignment` | `(contract, position, start_date)` | — |
| `WorkScheduleDay` | `(work_schedule, weekday)` | — |
| `ScheduleAssignment` | `(contract, start_date)` | — |
| `AttendanceEntry` | `(employee, work_date, check_in_at)` | — |
| `AttendanceIncident` | `(employee, work_date, incident_type)` | — |
| `LeaveType` / `DocumentType` / `WorkSchedule` | `code` | — |
| `LeaveEntitlement` | `(employee, leave_type, period_start)` | — |
| `LeaveRequest` | `public_id` | — |
| `EmployeeDocument` | `public_id` / `stored_path` | — |
| `Payslip` | `(run, employee)` | — |

### 3.2 `UniqueConstraint` parciales (`condition=`)

Son el mecanismo por el que las reglas de "solo uno vigente" llegan al motor.
Funcionan en SQLite y en PostgreSQL como índice único parcial.

| Entidad | Campos | Condición | Regla |
|---|---|---|---|
| `EmploymentContract` | `employee` | `status IN ('ACTIVE', 'SUSPENDED')` | **RN-13** |
| `AccountActivationCode` | `user` | `status = 'PENDING'` | Un solo código pendiente por usuario |
| `ContractSalary` | `contract` | `effective_to IS NULL` | RN-20 |
| `Assignment` | `contract` | `end_date IS NULL AND is_primary` | RN-24 |
| `DepartmentHeadship` | `department` | `end_date IS NULL` | RN-32 |
| `ScheduleAssignment` | `contract` | `end_date IS NULL` | — |
| `ContactMethod` | `(person, contact_type)` | `is_primary` | RN-05 |
| `Address` | `person` | `is_primary` | RN-06 |
| `IdentityDocument` | `(person, document_type, issuing_country)` | documento vigente | RN-03 |
| `EmployeeDocument` | `(employee, document_type, checksum_sha256)` | `is_active` | — |

> **Nota sobre RN-03:** la condición "vigente" no puede referirse a
> `CURRENT_DATE` dentro de un índice (no es inmutable en PostgreSQL). La
> condición efectiva será `expires_on IS NULL`, cubriendo el caso de documentos
> permanentes, y la validación de vigencia por fecha queda en el servicio. Se
> deja registrado para no descubrirlo en la migración.

### 3.3 `CheckConstraint`

| Entidad | Constraint | Regla |
|---|---|---|
| `Person` | `birth_date < CURRENT_DATE` (vía validador + check de rango razonable) | RN-04 |
| `Employee` | `termination_date IS NULL OR termination_date >= hire_date` | RN-17 |
| `Employee` | `(status='TERMINATED') = (termination_date IS NOT NULL)` | — |
| `Employee` | `employment_status IN (...)` | Regla 20 |
| `AccountActivationCode` | `expires_at > created_at` | — |
| `AccountActivationCode` | `(status='PENDING') = (resolved_at IS NULL)` | — |
| `EmploymentContract` | `end_date IS NULL OR start_date <= end_date` | RN-10 |
| `EmploymentContract` | `contract_type <> 'FIXED_TERM' OR end_date IS NOT NULL` | RN-12 |
| `EmploymentContract` | `probation_end_date IS NULL OR probation_end_date >= start_date` | RN-15 |
| `EmploymentContract` | `status <> 'TERMINATED' OR (termination_date IS NOT NULL AND termination_reason IS NOT NULL)` | RN-16 |
| `EmploymentContract` | `contract_type IN (...)`, `status IN (...)` | Regla 20 |
| `ContractSalary` | `amount > 0` | RN-22 |
| `ContractSalary` | `effective_to IS NULL OR effective_from <= effective_to` | — |
| `Assignment` | `end_date IS NULL OR start_date <= end_date` | — |
| `Assignment` | `fte > 0 AND fte <= 1.00` | RN-25 (parcial) |
| `Department` | `parent_id <> id` | RN-31 (parcial) |
| `JobGrade` | `min_salary > 0 AND min_salary <= max_salary` | RN-34 |
| `WorkSchedule` | `weekly_hours > 0 AND weekly_hours <= 168` | — |
| `WorkScheduleDay` | `weekday BETWEEN 0 AND 6`, `start_time < end_time`, `break_minutes >= 0` | — |
| `AttendanceEntry` | `check_out_at IS NULL OR check_in_at < check_out_at` | RN-50 |
| `AttendanceEntry` | Único parcial `(employee)` donde `check_out_at IS NULL` | Un solo marcaje abierto por persona: marcar dos entradas seguidas es el error más común (Fase 5) |
| `ScheduleAssignment` | Único parcial `(contract)` donde `end_date IS NULL` | Una sola jornada vigente por contrato |
| `WorkSchedule` | `0 < weekly_hours <= 168`; `grace_minutes <= 120` | ADR-021 |
| `AttendanceIncident` | `status = OPEN` ⇔ `resolved_at IS NULL` | Resolver exige constancia de cuándo (RN-53) |
| `AttendanceIncident` | `minutes >= 0` | — |
| `LeaveRequest` | `start_date <= end_date`, `working_days > 0` | RN-40 |
| `LeaveRequest` | Decidida ⇒ `decided_at` presente; pendiente ⇒ ausente; cancelada ⇒ cualquiera | Una aprobada y luego cancelada conserva su constancia (Fase 6, H-6) |
| `LeaveEntitlement` | `period_start < period_end`, `granted_days >= 0` | — |
| `LeaveType` | `max_backdating_days <= 30`; `min_notice_days = 0 OR max_backdating_days = 0` | ADR-022 §5 |
| `LeaveAccrualTier` | Único `(leave_type, min_years_of_service)`; `min_years_of_service >= 1`; `0 <= annual_days <= 60` | ADR-022 §6. Que un tramo no baje del piso ni de uno menor lo imponen los servicios (comparación entre filas) |
| `LeaveLedgerEntry` | `days <> 0` y signo coherente con `entry_type` | ADR-015 |
| `LeaveLedgerEntry` | Consumo y reversa exigen `request_id` | RN-46 |
| `LeaveRequestTransition` | `from_status <> to_status` | — |
| `EmployeeDocument` | `size_bytes > 0`, `length(checksum_sha256) = 64` | — |
| `EmployeeDocument` | `expires_on` nunca anterior a `issued_on` | — |
| `EmployeeDocument` | Único parcial `(employee, document_type, checksum_sha256)` donde `is_active = TRUE` | El mismo archivo una sola vez; archivar lo libera (ADR-023) |
| `DocumentType` | `max_size_mb > 0 AND max_size_mb <= 25`, `retention_years <= 50` | §K.4 |
| Todos los `status`/`type` | `IN (...)` con los valores del `TextChoices` | Regla 20 |

**Por qué duplicar `choices` con un `CheckConstraint`:** `choices` solo se valida
en `full_clean()`, que Django **no** ejecuta en `create()`, `update()` ni
`bulk_create()`. Sin el constraint, un `queryset.update(status="hacked")` entra
sin resistencia. La integridad no puede depender de que todo el código recuerde
llamar a `full_clean()` (regla 18).

### 3.4 Reglas no declarativas

Ver la tabla completa en [E.4](04-normalizacion.md#e4-anomalías-que-el-modelo-no-puede-evitar-por-sí-solo).
Resumen: los **no traslapes** (RN-14, RN-21, RN-41, RN-51), las **agregaciones**
(RN-25, RN-43) y la **aciclicidad** (RN-31) se aplican en `services.py` dentro de
`transaction.atomic()` con bloqueo de fila, y cada una tiene un test de frontera.

---

## 4. Índices

Se crean **a partir de consultas reales identificadas**, no por intuición
(regla 23). Cada índice lista la consulta que lo justifica. Los índices implícitos
de FK que Django ya crea no se repiten.

| # | Índice | Consulta que lo justifica |
|---|---|---|
| I-01 | `Employee(employment_status)` | Listado principal: empleados activos, filtro por defecto en todas las pantallas |
| I-02 | `Employee(public_id)` (único) | Resolución de la URL de detalle |
| I-03 | `Employee(employee_code)` (único) | Búsqueda por código, la más usada por RRHH |
| I-04 | `Person(last_name, first_name)` | Búsqueda y orden alfabético del listado |
| I-05 | `EmploymentContract(employee_id, status)` | "Contrato activo del empleado X" — se ejecuta en cada verificación de permiso |
| I-06 | `EmploymentContract(status, end_date)` | Proceso de vencimientos y alertas de fin de contrato |
| I-07 | `ContractSalary(contract_id, effective_from DESC)` | "Salario vigente del contrato X" |
| I-08 | `Assignment(contract_id, end_date)` | "Asignación vigente del contrato X" |
| I-09 | `Assignment(position_id, end_date)` + `Position(department_id)` | **Autorización de MANAGER:** "empleados vigentes del departamento X", que tras ADR-011 se resuelve por `position__department` |
| I-10 | `DepartmentHeadship(employee_id, end_date)` | **Autorización de MANAGER:** "departamentos que jefea el usuario hoy" |
| I-11 | `Department(parent_id)` | Recorrido del organigrama |
| I-12 | `AttendanceEntry(employee_id, work_date)` | Vista de asistencia mensual |
| I-13 | `AttendanceIncident(status, work_date)` | Bandeja de incidencias abiertas |
| I-14 | `LeaveRequest(employee_id, status)` | "Mis solicitudes" |
| I-15 | `LeaveRequest(status, start_date)` | Bandeja de aprobaciones pendientes |
| I-16 | `LeaveLedgerEntry(employee_id, leave_type_id, effective_date)` | Cálculo del saldo (agregación) |
| I-17 | `EmployeeDocument(employee_id, document_type_id)` | Expediente por categorías |
| I-18 | `EmployeeDocument(expires_on)` parcial `WHERE is_active` | Alerta de vencimientos |
| I-18b | `AccountActivationCode(user_id, status)` | Comprobar si un usuario ya tiene un código pendiente antes de emitir otro |
| I-19 | `AuditEvent(occurred_at DESC)` | Vista de auditoría, orden por defecto |
| I-20 | `AuditEvent(actor_id, occurred_at)` | "Todo lo que hizo el usuario X" — investigación de incidentes |
| I-21 | `AuditEvent(object_type, object_id)` | "Historial de este empleado" |
| I-22 | `AuditEvent(action, occurred_at)` | "Todos los `LOGIN_FAILED` de la última hora" — detección de fuerza bruta |
| I-23 | `Payslip(run_id, employee_id)` (único) | — |

**Criterio de revisión:** ningún índice se añade sin (a) una consulta concreta,
(b) evidencia de que se ejecuta con frecuencia o sobre volumen relevante. Se
revisan tras la Fase 3 con datos de prueba realistas (10k empleados) usando
`EXPLAIN QUERY PLAN` y `django-debug-toolbar` en desarrollo.

**Índices deliberadamente NO creados:**

| Descartado | Motivo |
|---|---|
| `Person(first_name)` aislado | Cubierto por I-04 |
| Índices en todos los booleanos (`is_active`) | Baja cardinalidad; el planificador los ignora salvo en índices parciales |
| Índices de texto completo | SQLite FTS5 no es portable a PostgreSQL sin reescribir. La búsqueda usa `icontains` hasta que el volumen lo justifique; entonces se migrará a `SearchVector` de PostgreSQL (ADR-003) |

---

## 5. Preparación para PostgreSQL

Compromisos asumidos hoy para que la migración (ADR-003) no sea una reescritura:

| Área | Decisión en SQLite | Qué cambia en PostgreSQL |
|---|---|---|
| Tipos | Solo tipos estándar de Django | Nada |
| Consultas | ORM exclusivamente; sin `RawSQL` sin aprobación | Nada |
| Decimales | `DecimalField` con precisión declarada | **SQLite no la valida**; PostgreSQL sí. Los tests de dinero deben correr también en PostgreSQL en CI antes de producción |
| Fechas/horas | `USE_TZ=True` desde el día uno | `timestamptz` nativo. Sin migración de datos |
| No traslape | Validación en servicio + tests | Se promueve a `ExclusionConstraint` con `daterange` + `btree_gist`, manteniendo la validación de servicio para los mensajes de error |
| Unicidad case-insensitive de `email` | Normalización a minúsculas en `save()` | Se puede reforzar con `CITEXT` o un `UniqueConstraint` sobre `Lower("email")` |
| Búsqueda de texto | `icontains` | `SearchVector` + índice GIN |
| JSON | `JSONField` sin operadores específicos | `jsonb` con índices GIN si hace falta |
| Migraciones | Siempre generadas por Django, nunca SQL manual (regla 26) | Se reproducen sobre una base vacía en CI |

**Verificación continua:** desde la Fase 1, el pipeline de CI ejecuta la suite
completa **también** contra PostgreSQL en un job separado (servicio de contenedor
de GitHub Actions). Es barato ahora y detecta divergencias en el momento en que
se introducen, en lugar de el día de la migración.
