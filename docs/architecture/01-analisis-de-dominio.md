# A. Análisis del dominio

> Fase 0 — Documento de diseño. **No existe código todavía.** Este documento debe
> ser revisado y aprobado antes de escribir modelos Django (regla 69).

---

## A.0 Supuestos y decisiones pendientes

El dominio de RRHH es fuertemente dependiente de la jurisdicción laboral. El
diseño se elabora bajo los siguientes **supuestos explícitos**. Cada uno cambia
el modelo si se responde distinto, por lo que deben confirmarse antes de la
Fase 3.

| # | Supuesto asumido | Impacto si es falso | Prioridad |
|---|---|---|---|
| S-01 | Jurisdicción **Guatemala** (DPI/CUI, NIT, IGSS, Código de Trabajo: aguinaldo, bono 14, 15 días hábiles de vacaciones) | Cambia catálogos de identificadores, tipos de ausencia y todo el dominio de nómina | Alta |
| S-02 | **Una sola entidad legal (empresa)** operando el sistema | Retrofit multi-empresa es caro. Ver mitigación en A.5 | Alta |
| S-03 | Moneda única **GTQ**, sin conversión ni multimoneda | Exigiría tipo de cambio histórico y una entidad `ExchangeRate` | Media |
| ~~S-04~~ | **Resuelto.** No existe auto-registro público: RRHH invita por correo (Fase 2) y entrega códigos de activación al personal sin correo (Fase 6). El alcance de cuentas de la Fase 2 son RRHH y jefaturas | Ver [ADR-004](../decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md) | ✔ |
| S-05 | Un empleado tiene **como máximo un contrato vigente** a la vez | Elimina el `UniqueConstraint` parcial de contrato activo | Alta |
| S-06 | La aprobación de ausencias es de **un solo nivel** (jefe de departamento o RRHH) | Un workflow multinivel exige una entidad `ApprovalStep` | Media |
| S-07 | Zona horaria `America/Guatemala`, almacenamiento en UTC (`USE_TZ=True`) | — | Baja |
| S-08 | Retención: los registros laborales y de nómina se conservan **indefinidamente**; no hay borrado físico de historia | Cambia la política de borrado y exige un proceso de purga | Media |

**Decisiones abiertas que requieren respuesta del negocio** (no bloquean la
Fase 1, sí la Fase 3):

- ¿Se contempla **recontratación** de un ex-empleado? (afecta si `Person` puede
  tener más de un `Employee`, ver A.2.1).
- ~~¿Los puestos son globales o pertenecen a un departamento?~~ **Resuelto:**
  pertenecen a un departamento; ningún título es transversal y el perfil se define
  por área ([ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md)).
- ¿Existen empleados con **asignación múltiple** (matriz / dos departamentos)?
- ¿Marcaje de asistencia manual, biométrico o ambos?

---

## A.1 Contextos delimitados (bounded contexts)

El sistema se organiza en contextos con fronteras explícitas. Cada contexto se
implementa como una app Django (monolito modular) y **solo** se comunica con
otros a través de su interfaz pública documentada (`services.py`, `selectors.py`).

| Contexto | Responsabilidad | Depende de |
|---|---|---|
| `core` | Primitivas compartidas: modelos abstractos, validadores, catálogos transversales (empresa, feriados), utilidades de fecha | — |
| `accounts` | Identidad de acceso: usuario, credenciales, roles, sesión | `core` |
| `departments` | Estructura organizacional y jefaturas | `core`, `employees` (jefatura) |
| `positions` | Puestos (que pertenecen a un departamento) y bandas salariales | `core`, `departments` |
| `employees` | Identidad de la persona y del empleado, contacto, identificadores | `core`, `accounts` |
| `contracts` | Relación laboral: contratos, salarios, asignación a puestos | `employees`, `positions` |
| `attendance` | Jornadas, marcajes, incidencias | `contracts`, `core` |
| `leave` | Tipos de ausencia, solicitudes, derechos y saldos | `contracts`, `core` |
| `documents` | Expediente digital y acceso controlado a archivos | `employees`, `accounts` |
| `payroll` | Períodos, corridas y recibos de nómina (Fase 8) | `contracts`, `attendance`, `leave` |
| `audit` | Registro append-only de eventos relevantes | `accounts` |

**Regla de dependencia:** el grafo es acíclico salvo la relación
`departments ↔ employees`, que existe porque una jefatura apunta a un empleado.
Se rompe con referencias por string (`"employees.Employee"`).

Tras [ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md),
`contracts` **ya no depende de `departments`**: la asignación apunta al puesto, y
el puesto es quien conoce su departamento. Una decisión de normalización acabó
simplificando también el grafo de dependencias entre apps.

---

## A.2 Entidades y agregados

Se identifican cinco agregados. El **raíz de agregado** es la única entidad por
la que se modifica el conjunto; las entidades internas no se crean ni editan
fuera de los servicios del agregado.

### A.2.1 Agregado `Person` / `Employee` (contexto `employees`)

**Raíz: `Employee`** (con `Person` como entidad de identidad civil).

| Entidad | Rol | Justificación de existencia separada |
|---|---|---|
| `Person` | Identidad civil: nombres, fecha de nacimiento, género, estado civil, nacionalidad | Tiene identidad y ciclo de vida propios. Una persona existe antes y después de ser empleada |
| `Employee` | Identidad laboral: código de empleado, fecha de ingreso, estado de vinculación | Atributos y reglas propias, distintas de la identidad civil |
| `IdentityDocument` | DPI/CUI, NIT, IGSS, pasaporte, licencia | Atributo **multivaluado**: una persona tiene N documentos. Modelarlo como columnas viola 1NF y obliga a migrar el esquema por cada nuevo tipo |
| `ContactMethod` | Teléfonos y correos personales | Multivaluado. Prohíbe explícitamente `phones = "5551111,5552222"` |
| `Address` | Domicilio, dirección de correspondencia | Multivaluado y con estructura propia |
| `EmergencyContact` | Contacto de emergencia | Es una persona **externa** al sistema; no se promueve a `Person` porque no tiene ciclo de vida propio aquí |

**Por qué `Person` ≠ `Employee`** (regla 13): el modelo `Employee` gigante mezcla
identidad civil, contacto, contrato, nómina y documentos. Al separar, la fuente
de verdad de "cómo se llama" es `Person`, y la de "desde cuándo trabaja aquí" es
`Employee`.

**Cardinalidad `Person` → `Employee`:** se define **1:1** (`OneToOne`) bajo el
supuesto de que la recontratación se modela como un **nuevo contrato** sobre el
mismo `Employee`, conservando el código de empleado. Si el negocio exige que un
recontratado reciba código nuevo y expediente separado, la relación pasa a 1:N.
**Requiere confirmación.**

### A.2.2 Agregado `EmploymentContract` (contexto `contracts`)

**Raíz: `EmploymentContract`.** Es el agregado más importante del sistema:
concentra las condiciones legales de la relación laboral.

| Entidad | Rol |
|---|---|
| `EmploymentContract` | Tipo de contrato, vigencia, período de prueba, estado, causa de terminación |
| `ContractSalary` | Historial salarial: monto vigente desde una fecha, con motivo del cambio |
| `Assignment` | Ocupación de un puesto con vigencia, FTE y marca de principal. El departamento se deriva del puesto (ADR-011) |

**Por qué salario y asignación cuelgan del contrato y no del empleado:** el
salario y el puesto son **cláusulas del contrato**. Colgarlos de `Employee`
obligaría a duplicar la vigencia y permitiría estados imposibles (salario activo
sin contrato activo). La consulta "salario actual del empleado X" se resuelve por
join en un `selector`, no duplicando la FK.

### A.2.3 Agregado `Department` (contexto `departments`)

| Entidad | Rol |
|---|---|
| `Department` | Nodo del organigrama: código, nombre, padre, centro de costo |
| `DepartmentHeadship` | Jefatura del departamento con vigencia |

**Por qué la jefatura es temporal y no una columna `manager_id`:** la cadena de
aprobación de una ausencia debe poder reconstruirse *tal como era* en la fecha de
la decisión. Con una columna mutable se pierde esa trazabilidad y se genera una
anomalía de actualización (cambiar de jefe reescribe la historia).

### A.2.4 Agregado `LeaveRequest` (contexto `leave`)

| Entidad | Rol |
|---|---|
| `LeaveType` | Catálogo: vacaciones, enfermedad (IGSS), maternidad, permiso sin goce, duelo |
| `LeaveEntitlement` | Derecho devengado por período (ej. 15 días hábiles del período 2026) |
| `LeaveRequest` | Solicitud con rango, días hábiles calculados y estado |
| `LeaveRequestTransition` | Historial de decisiones: quién aprobó/rechazó, cuándo, con qué nota |
| `LeaveLedgerEntry` | Asiento de días: devengo, consumo, ajuste, vencimiento |

**Por qué un libro mayor (`ledger`) en lugar de un campo `balance`:** un campo
`taken_days` mutable sufre anomalías de actualización (una solicitud cancelada
obliga a recalcular y puede desincronizarse silenciosamente). El saldo es
`SUM(days)` sobre el ledger: auditable, reconstruible y sin estado duplicado. Si
la medición demuestra un problema de rendimiento, se materializa después
(regla 51: optimizar tras medir).

### A.2.5 Agregado `PayrollRun` (contexto `payroll`, Fase 8)

| Entidad | Rol |
|---|---|
| `PayrollPeriod` | Período de cálculo (quincena/mes) |
| `PayrollRun` | Corrida de nómina sobre un período, con estado y bloqueo |
| `Payslip` | Recibo por empleado: **snapshot** de nombre, puesto, departamento y salario |
| `PayslipLine` | Renglón: concepto, tipo (ingreso/deducción/costo patronal), monto |
| `PayrollConcept` | Catálogo de conceptos con su naturaleza y base de cálculo |

El snapshot en `Payslip` es una duplicación **deliberada y justificada** (regla 16):
un recibo es un documento legal e inmutable; debe seguir mostrando el puesto que
el empleado tenía ese mes aunque hoy sea otro.

### A.2.6 Entidades transversales

| Entidad | Contexto | Rol |
|---|---|---|
| `Company` | `core` | Entidad legal empleadora (ver A.5) |
| `Holiday` | `core` | Feriados oficiales; necesario para contar días hábiles |
| `User` | `accounts` | Credencial de acceso. **No** es el empleado |
| `AuditEvent` | `audit` | Evento append-only |
| `DocumentType` / `EmployeeDocument` | `documents` | Expediente digital |
| `WorkSchedule` / `WorkScheduleDay` / `ScheduleAssignment` | `attendance` | Jornada laboral pactada |
| `AttendanceEntry` / `AttendanceIncident` | `attendance` | Marcajes e incidencias |
| `JobGrade` / `Position` | `positions` | Banda salarial y puesto |

**Por qué `User` ≠ `Employee`:** no todo empleado tiene acceso al sistema (personal
operativo sin correo) y no todo usuario es empleado (auditor externo, integración).
Acoplarlos obliga a crear credenciales fantasma y expande la superficie de ataque.
La relación es `Employee.user` opcional (0..1).

---

## A.3 Relaciones y cardinalidades

| Origen | Destino | Card. | Opcionalidad | Propietario | Regla de dominio |
|---|---|---|---|---|---|
| `Person` | `Employee` | 1:1 | Employee obligatorio → Person | `Employee` | Todo empleado es una persona |
| `User` | `Employee` | 1:0..1 | Ambos lados opcionales | `Employee` | Un usuario representa a lo sumo un empleado |
| `Person` | `IdentityDocument` | 1:N | ≥0 | `Person` | Un documento pertenece a una sola persona |
| `Person` | `ContactMethod` | 1:N | ≥0 | `Person` | A lo sumo un principal por tipo |
| `Person` | `Address` | 1:N | ≥0 | `Person` | A lo sumo una principal |
| `Employee` | `EmergencyContact` | 1:N | ≥0 | `Employee` | Prioridad única por empleado |
| `Employee` | `EmploymentContract` | 1:N | ≥0 | `Employee` | Máximo **uno activo** simultáneo |
| `Company` | `EmploymentContract` | 1:N | obligatorio | `Company` | El contrato se firma con una entidad legal |
| `EmploymentContract` | `ContractSalary` | 1:N | ≥1 | `Contract` | Exactamente uno vigente (sin fecha fin) |
| `EmploymentContract` | `Assignment` | 1:N | ≥1 | `Contract` | Exactamente una principal vigente |
| `Position` | `Assignment` | 1:N | obligatorio | `Position` | El departamento se deriva del puesto |
| `Department` | `Position` | 1:N | obligatorio | `Department` | Un puesto pertenece a un área (ADR-011) |
| `JobGrade` | `Position` | 1:N | obligatorio | `JobGrade` | El puesto hereda la banda salarial |
| `Department` | `Department` | 1:N (auto) | padre opcional | — | Jerarquía sin ciclos |
| `Department` | `DepartmentHeadship` | 1:N | ≥0 | `Department` | Máximo un jefe vigente |
| `Employee` | `DepartmentHeadship` | 1:N | — | — | Un empleado puede jefear varios departamentos |
| `Employee` | `LeaveRequest` | 1:N | ≥0 | `Employee` | — |
| `LeaveType` | `LeaveRequest` | 1:N | obligatorio | `LeaveType` | — |
| `LeaveRequest` | `LeaveRequestTransition` | 1:N | ≥1 | `LeaveRequest` | Append-only |
| `LeaveRequest` | `LeaveLedgerEntry` | 1:0..N | opcional | `LeaveRequest` | El consumo se asienta al aprobar |
| `Employee` | `AttendanceEntry` | 1:N | ≥0 | `Employee` | Segmentos sin traslape en el mismo día |
| `Employee` | `EmployeeDocument` | 1:N | ≥0 | `Employee` | — |
| `PayrollRun` | `Payslip` | 1:N | ≥0 | `PayrollRun` | Único por (corrida, empleado) |
| `User` | `AuditEvent` | 1:N | actor opcional | `AuditEvent` | El evento sobrevive al usuario |

**No hay ninguna relación N:M implementada con `ManyToManyField` puro.** Todas
las relaciones muchos-a-muchos del dominio (empleado↔departamento,
empleado↔puesto, empleado↔tipo de ausencia) tienen atributos propios (vigencia,
FTE, principal) y por tanto se modelan como **entidades asociativas explícitas**
(regla 8). Las únicas M:M sin atributos son las de Django (`User↔Group`,
`Group↔Permission`), propias del framework.

---

## A.4 Reglas de negocio

Numeradas para poder referenciarlas desde constraints y tests.

### Identidad y empleado
- **RN-01** El `employee_code` es único en todo el sistema y no se reutiliza tras una baja.
- **RN-02** Un `IdentityDocument` es único por (tipo, número, país emisor).
- **RN-03** Una persona no puede tener dos documentos vigentes del mismo tipo y país.
- **RN-04** `Person.birth_date` debe ser pasada y la persona debe tener ≥ 18 años a la fecha de ingreso (confirmar excepciones legales).
- **RN-05** A lo sumo un `ContactMethod` principal por tipo y persona.
- **RN-06** A lo sumo una `Address` principal por persona.

### Contrato
- **RN-10** `start_date <= end_date` cuando `end_date` no es nulo.
- **RN-11** Un contrato indefinido no puede tener `end_date` salvo que su estado sea `TERMINATED`.
- **RN-12** Un contrato de plazo fijo **debe** tener `end_date`.
- **RN-13** Un empleado no puede tener dos contratos en estado `ACTIVE` simultáneamente.
- **RN-14** Los rangos de contratos del mismo empleado no se traslapan.
- **RN-15** `probation_end_date`, si existe, cae dentro del rango del contrato.
- **RN-16** Terminar un contrato exige `termination_date` y `termination_reason`.
- **RN-17** `termination_date` ≥ `start_date`.
- **RN-18** `Employee.employment_status` debe ser coherente con la existencia de un contrato activo (invariante verificada por servicio y test).

### Salario y asignación
- **RN-20** Todo contrato tiene exactamente un `ContractSalary` con `effective_to IS NULL` (el vigente).
- **RN-21** Los períodos de `ContractSalary` de un contrato no se traslapan ni dejan huecos.
- **RN-22** `amount > 0` y ≥ salario mínimo vigente (parámetro configurable, no constante en código).
- **RN-23** El salario debe estar dentro de `[min_salary, max_salary]` del `JobGrade` del puesto asignado; fuera de banda requiere autorización explícita registrada.
- **RN-24** Todo contrato tiene exactamente una `Assignment` principal vigente.
- **RN-25** La suma de FTE de las asignaciones vigentes de un contrato es ≤ 1.00.
- **RN-26** El rango de una `Assignment` está contenido en el rango de su contrato.

### Organización
- **RN-30** `Department.code` único por empresa.
- **RN-31** La jerarquía de departamentos es acíclica.
- **RN-32** Máximo una `DepartmentHeadship` vigente por departamento.
- **RN-33** No se puede desactivar un departamento cuyos puestos tengan asignaciones vigentes.
- **RN-34** `JobGrade.min_salary <= JobGrade.max_salary`.
- **RN-35** El título de un puesto es único dentro de su departamento (ADR-011).

### Ausencias
- **RN-40** `LeaveRequest.start_date <= end_date`.
- **RN-41** Las solicitudes aprobadas o pendientes de un mismo empleado no se traslapan.
- **RN-42** Los días solicitados se calculan en **días hábiles**, excluyendo descansos según la jornada pactada y los `Holiday` vigentes.
- **RN-43** No se puede aprobar una solicitud cuyo consumo deje el saldo negativo, salvo tipos que lo permitan explícitamente.
- **RN-44** El aprobador no puede ser el propio solicitante (separación de funciones).
- **RN-45** Transiciones válidas: `DRAFT → SUBMITTED → (APPROVED | REJECTED)`; `SUBMITTED → CANCELLED`; `APPROVED → CANCELLED` solo antes de la fecha de inicio y por RRHH.
- **RN-46** Aprobar asienta un `LeaveLedgerEntry` de consumo; cancelar asienta la reversa. **Nunca se edita ni borra un asiento.**

### Asistencia
- **RN-50** `check_out_at > check_in_at` en el mismo segmento.
- **RN-51** Los segmentos de un empleado en un mismo día no se traslapan.
- **RN-52** No se registran marcajes en fechas sin contrato activo.
- **RN-53** Una incidencia justificada requiere actor, fecha y motivo.

### Documentos
- **RN-60** Un documento pertenece a un empleado y a un tipo del catálogo.
- **RN-61** Un tipo marcado como sensible solo es visible para RRHH y el propio empleado.
- **RN-62** Todo acceso (subida, descarga, borrado) genera un `AuditEvent`.
- **RN-63** Los documentos con vencimiento generan alerta antes de expirar.

### Auditoría
- **RN-70** `AuditEvent` es **append-only**: sin update ni delete desde la aplicación.
- **RN-71** El evento conserva una representación textual del actor y del objeto para sobrevivir a su borrado.
- **RN-72** Nunca se registran contraseñas, tokens, cookies ni el contenido de documentos.

---

## A.5 Multi-empresa: decisión anticipada

Se incluye una entidad `Company` **desde el inicio**, con una sola fila en la
práctica, referenciada únicamente por `Department` y `EmploymentContract`.

**Justificación (no es sobreingeniería):** es la única decisión de este diseño
cuyo retrofit posterior resulta desproporcionadamente caro — obligaría a añadir
una FK no nula a media docena de tablas con datos ya cargados, a reescribir todos
los `UniqueConstraint` (`code` pasa de único global a único por empresa) y a
revisar cada selector de autorización. El costo hoy es una tabla y dos FKs; el
costo mañana es una migración de datos con riesgo. Se documenta como **ADR-010**.

Si el negocio confirma que jamás habrá una segunda entidad legal, se elimina
antes de la Fase 3 con costo cero.

---

## A.6 Fuera de alcance (YAGNI explícito)

Se identifican y **descartan conscientemente** para esta iteración:

| Descartado | Motivo | ¿Cuándo reconsiderar? |
|---|---|---|
| Reclutamiento / ATS (vacantes, candidatos) | Dominio distinto, con su propio ciclo de vida | Fase 9+ |
| Evaluación de desempeño | Requiere modelo de objetivos y ciclos | Fase 9+ |
| Capacitaciones y competencias (`Skill`) | Multivaluado, fácil de añadir después sin romper nada | Cuando exista requisito |
| Catálogo geográfico completo (departamento/municipio) | Se guarda como texto + país ISO; añadir catálogo después es una migración local | Si se requiere reportería geográfica |
| Multimoneda con tipo de cambio | Supuesto S-03 | Si aparece una segunda moneda |
| Workflow de aprobación multinivel | Supuesto S-06 | Si RRHH lo exige |
| `EmploymentEvent` (historial de estado del empleado) | Redundante: la historia está en contratos + auditoría | Si la reportería lo demanda |
