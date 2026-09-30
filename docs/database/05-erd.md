# F. Diagrama entidad-relación (ERD)

Los diagramas se escriben en **Mermaid** para que sean versionables en Git y
revisables en un diff (regla 24). Se mantienen sincronizados con el modelo: todo
cambio de esquema que altere una entidad o una relación **debe** actualizar este
archivo en el mismo commit.

Notación de cardinalidad Mermaid usada:

| Símbolo | Significado |
|---|---|
| `\|\|--\|\|` | uno y solo uno ↔ uno y solo uno |
| `\|\|--o{` | uno ↔ cero o muchos |
| `\|\|--\|{` | uno ↔ uno o muchos |
| `}o--\|\|` | cero o muchos ↔ uno |
| `\|o--o\|` | cero o uno ↔ cero o uno |

---

## F.1 Vista global

Relaciones únicamente, sin atributos, para poder leer la estructura completa.
Las entidades de nómina (Fase 8) se muestran en gris conceptual: su diseño
detallado es posterior.

```mermaid
erDiagram
    COMPANY ||--o{ DEPARTMENT : "opera"
    COMPANY ||--o{ EMPLOYMENT_CONTRACT : "firma"
    COMPANY ||--o{ HOLIDAY : "define"

    USER |o--o| EMPLOYEE : "accede como"
    USER ||--o{ AUDIT_EVENT : "genera"
    USER ||--o{ ACCOUNT_ACTIVATION_CODE : "activa con"

    PERSON ||--|| EMPLOYEE : "es"
    PERSON ||--o{ IDENTITY_DOCUMENT : "se identifica con"
    PERSON ||--o{ CONTACT_METHOD : "se contacta por"
    PERSON ||--o{ ADDRESS : "reside en"

    EMPLOYEE ||--o{ EMERGENCY_CONTACT : "declara"
    EMPLOYEE ||--o{ EMPLOYMENT_CONTRACT : "mantiene"
    EMPLOYEE ||--o{ DEPARTMENT_HEADSHIP : "jefatura"
    EMPLOYEE ||--o{ LEAVE_REQUEST : "solicita"
    EMPLOYEE ||--o{ LEAVE_ENTITLEMENT : "acumula"
    EMPLOYEE ||--o{ LEAVE_LEDGER_ENTRY : "registra"
    EMPLOYEE ||--o{ ATTENDANCE_ENTRY : "marca"
    EMPLOYEE ||--o{ ATTENDANCE_INCIDENT : "incurre en"
    EMPLOYEE ||--o{ EMPLOYEE_DOCUMENT : "archiva"
    EMPLOYEE ||--o{ PAYSLIP : "recibe"

    DEPARTMENT ||--o{ DEPARTMENT : "contiene"
    DEPARTMENT ||--o{ DEPARTMENT_HEADSHIP : "es dirigido por"
    DEPARTMENT ||--o{ POSITION : "define"

    JOB_GRADE ||--o{ POSITION : "clasifica"
    POSITION ||--o{ ASSIGNMENT : "se ejerce como"

    EMPLOYMENT_CONTRACT ||--|{ CONTRACT_SALARY : "estipula"
    EMPLOYMENT_CONTRACT ||--|{ ASSIGNMENT : "asigna"
    EMPLOYMENT_CONTRACT ||--o{ SCHEDULE_ASSIGNMENT : "pacta jornada"

    WORK_SCHEDULE ||--|{ WORK_SCHEDULE_DAY : "detalla"
    WORK_SCHEDULE ||--o{ SCHEDULE_ASSIGNMENT : "se aplica en"

    LEAVE_TYPE ||--o{ LEAVE_REQUEST : "clasifica"
    LEAVE_TYPE ||--o{ LEAVE_ENTITLEMENT : "otorga"
    LEAVE_TYPE ||--o{ LEAVE_LEDGER_ENTRY : "contabiliza"
    LEAVE_REQUEST ||--|{ LEAVE_REQUEST_TRANSITION : "transiciona"
    LEAVE_REQUEST ||--o{ LEAVE_LEDGER_ENTRY : "consume"

    DOCUMENT_TYPE ||--o{ EMPLOYEE_DOCUMENT : "tipifica"

    PAYROLL_PERIOD ||--o{ PAYROLL_RUN : "se calcula en"
    PAYROLL_RUN ||--o{ PAYSLIP : "produce"
    PAYSLIP ||--|{ PAYSLIP_LINE : "detalla"
    PAYROLL_CONCEPT ||--o{ PAYSLIP_LINE : "clasifica"
```

**Lecturas clave del diagrama:**

1. `EMPLOYEE` tiene muchas relaciones salientes pero **pocos atributos propios**:
   es un nodo de identidad, no un depósito de datos (regla 13).
2. No hay ninguna arista directa `EMPLOYEE → DEPARTMENT` ni `EMPLOYEE → POSITION`.
   El camino es `EMPLOYEE → EMPLOYMENT_CONTRACT → ASSIGNMENT → POSITION → DEPARTMENT`,
   porque la ocupación de un puesto es un hecho con vigencia y el departamento se
   deriva del puesto.
3. `AUDIT_EVENT` solo se conecta con `USER`, y con FK opcional: la auditoría no
   depende del ciclo de vida de lo auditado.

---

## F.2 Núcleo de identidad (`accounts` + `employees`)

```mermaid
erDiagram
    USER {
        bigint id PK
        varchar email UK "normalizado a minúsculas"
        varchar password "hash Argon2/PBKDF2"
        bool is_active
        bool is_staff
        bool is_superuser
        bool must_change_password
        char language "preferencia de idioma (i18n)"
        datetime last_login
        datetime date_joined
    }

    ACCOUNT_ACTIVATION_CODE {
        bigint id PK
        bigint user_id FK "UNIQUE parcial si status=PENDING"
        char code_hash UK "HMAC-SHA256; el código en claro NUNCA se guarda"
        varchar status "PENDING|REDEEMED|REVOKED"
        datetime expires_at
        datetime resolved_at "nullable"
        bigint created_by_id FK "nullable"
    }

    PERSON {
        bigint id PK
        varchar first_name
        varchar middle_name "nullable"
        varchar last_name
        varchar second_last_name "nullable"
        date birth_date
        varchar gender "choices"
        varchar marital_status "choices"
        char nationality "ISO-3166-1 alfa-2"
    }

    EMPLOYEE {
        bigint id PK
        uuid public_id UK "usado en URLs"
        bigint person_id FK "UNIQUE - 1:1"
        bigint user_id FK "UNIQUE, nullable - 0..1"
        varchar employee_code UK
        date hire_date
        varchar employment_status "ACTIVE|ON_LEAVE|SUSPENDED|TERMINATED"
        date termination_date "nullable"
    }

    IDENTITY_DOCUMENT {
        bigint id PK
        bigint person_id FK
        varchar document_type "DPI|NIT|IGSS|PASSPORT|DRIVER_LICENSE"
        varchar number
        char issuing_country
        date issued_on "nullable"
        date expires_on "nullable"
        bool is_primary
    }

    CONTACT_METHOD {
        bigint id PK
        bigint person_id FK
        varchar contact_type "MOBILE|LANDLINE|PERSONAL_EMAIL|WORK_EMAIL"
        varchar value
        bool is_primary "único por tipo"
    }

    ADDRESS {
        bigint id PK
        bigint person_id FK
        varchar address_type "HOME|MAILING"
        varchar line1
        varchar line2 "nullable"
        varchar locality
        varchar region
        varchar postal_code "nullable"
        char country
        bool is_primary
    }

    EMERGENCY_CONTACT {
        bigint id PK
        bigint employee_id FK
        varchar full_name
        varchar relationship "choices"
        varchar phone
        varchar alternate_phone "nullable"
        smallint priority "único por empleado"
    }

    USER |o--o| EMPLOYEE : "accede como"
    USER ||--o{ ACCOUNT_ACTIVATION_CODE : "activa con"
    PERSON ||--|| EMPLOYEE : "es"
    PERSON ||--o{ IDENTITY_DOCUMENT : "tiene"
    PERSON ||--o{ CONTACT_METHOD : "tiene"
    PERSON ||--o{ ADDRESS : "tiene"
    EMPLOYEE ||--o{ EMERGENCY_CONTACT : "declara"
```

---

## F.3 Organización y relación laboral (`departments` + `positions` + `contracts`)

Este es el subdominio donde se concentran las decisiones de normalización.

```mermaid
erDiagram
    COMPANY {
        bigint id PK
        varchar code UK
        varchar legal_name
        varchar tax_id UK
        char country
        bool is_active
    }

    DEPARTMENT {
        bigint id PK
        bigint company_id FK
        bigint parent_id FK "nullable, autorreferencia"
        varchar code "UK con company_id"
        varchar name
        varchar cost_center "nullable"
        bool is_active
    }

    DEPARTMENT_HEADSHIP {
        bigint id PK
        bigint department_id FK
        bigint employee_id FK
        date start_date
        date end_date "nullable = jefatura vigente"
    }

    JOB_GRADE {
        bigint id PK
        varchar code UK
        varchar name
        smallint level
        decimal min_salary
        decimal max_salary
        char currency "ISO-4217"
        bool is_active
    }

    POSITION {
        bigint id PK
        bigint department_id FK "el puesto pertenece a un area (ADR-011)"
        bigint job_grade_id FK
        varchar code UK
        varchar title "UK con department_id"
        text description "especifica del area"
        bool is_active
    }

    EMPLOYMENT_CONTRACT {
        bigint id PK
        uuid public_id UK
        bigint employee_id FK "UNIQUE parcial si status=ACTIVE"
        bigint company_id FK
        varchar contract_type "INDEFINITE|FIXED_TERM|TEMPORARY|INTERNSHIP"
        date start_date
        date end_date "nullable"
        date probation_end_date "nullable"
        varchar status "DRAFT|ACTIVE|SUSPENDED|TERMINATED|EXPIRED"
        varchar termination_reason "nullable"
        date termination_date "nullable"
        date signed_on "nullable"
    }

    CONTRACT_SALARY {
        bigint id PK
        bigint contract_id FK
        decimal amount
        char currency
        varchar pay_frequency "MONTHLY|BIWEEKLY|WEEKLY"
        date effective_from
        date effective_to "nullable = vigente"
        varchar change_reason
        bigint created_by_id FK "nullable"
    }

    ASSIGNMENT {
        bigint id PK
        bigint contract_id FK "NO hay employee_id: sería transitivo"
        bigint position_id FK
        bigint department_id FK
        date start_date
        date end_date "nullable = vigente"
        bool is_primary
        decimal fte "0 < fte <= 1.00"
    }

    COMPANY ||--o{ DEPARTMENT : "opera"
    COMPANY ||--o{ EMPLOYMENT_CONTRACT : "firma"
    DEPARTMENT ||--o{ DEPARTMENT : "contiene"
    DEPARTMENT ||--o{ DEPARTMENT_HEADSHIP : "dirigido por"
    EMPLOYEE ||--o{ DEPARTMENT_HEADSHIP : "dirige"
    JOB_GRADE ||--o{ POSITION : "clasifica"
    EMPLOYEE ||--o{ EMPLOYMENT_CONTRACT : "mantiene"
    EMPLOYMENT_CONTRACT ||--|{ CONTRACT_SALARY : "estipula"
    EMPLOYMENT_CONTRACT ||--|{ ASSIGNMENT : "asigna"
    POSITION ||--o{ ASSIGNMENT : "se ejerce como"
    DEPARTMENT ||--o{ POSITION : "define"
```

**Anotaciones de diseño visibles en el diagrama:**

- `ASSIGNMENT` es la **entidad asociativa** que resuelve la relación N:M
  empleado↔puesto. Lleva los atributos propios de la relación (`start_date`,
  `end_date`, `is_primary`, `fte`), tal como exige la regla 8.
- `ASSIGNMENT` **no contiene ninguna referencia redundante**, y las dos que
  faltan lo son por el mismo motivo: `employee_id` sería transitivo vía el
  contrato, y `department_id` sería transitivo vía el puesto
  ([§D.5.3](04-normalizacion.md#d5-tercera-forma-normal-3nf) y
  [§D.5.4](04-normalizacion.md#d5-tercera-forma-normal-3nf)).
- `POSITION` **sí** contiene `department_id`: el negocio confirmó que ningún
  título es transversal ([ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md)).
- El rango salarial vive en `JOB_GRADE`, no en `POSITION` (3NF).
- La jefatura es una entidad temporal, no una columna `manager_id`.

---

## F.4 Asistencia (`attendance`, Fase 5)

```mermaid
erDiagram
    WORK_SCHEDULE {
        bigint id PK
        varchar code UK
        varchar name
        decimal weekly_hours
        bool is_active
    }

    WORK_SCHEDULE_DAY {
        bigint id PK
        bigint work_schedule_id FK
        smallint weekday "0=lunes .. 6=domingo"
        time start_time
        time end_time
        smallint break_minutes
    }

    SCHEDULE_ASSIGNMENT {
        bigint id PK
        bigint contract_id FK
        bigint work_schedule_id FK
        date start_date
        date end_date "nullable = vigente"
    }

    ATTENDANCE_ENTRY {
        bigint id PK
        bigint employee_id FK
        date work_date
        datetime check_in_at
        datetime check_out_at "nullable = jornada abierta"
        varchar source "SELF|SUPERVISOR|HR|DEVICE|IMPORT"
        bigint registered_by_id FK "nullable"
        varchar note
    }

    ATTENDANCE_INCIDENT {
        bigint id PK
        bigint employee_id FK
        date work_date
        varchar incident_type "LATE|EARLY_LEAVE|ABSENCE|OVERTIME|MISSING_PUNCH"
        int minutes
        varchar status "OPEN|JUSTIFIED|REJECTED"
        text justification
        bigint resolved_by_id FK "nullable"
        datetime resolved_at "nullable"
    }

    WORK_SCHEDULE ||--|{ WORK_SCHEDULE_DAY : "detalla"
    WORK_SCHEDULE ||--o{ SCHEDULE_ASSIGNMENT : "se aplica en"
    EMPLOYMENT_CONTRACT ||--o{ SCHEDULE_ASSIGNMENT : "pacta"
    EMPLOYEE ||--o{ ATTENDANCE_ENTRY : "marca"
    EMPLOYEE ||--o{ ATTENDANCE_INCIDENT : "incurre en"
```

> `ATTENDANCE_ENTRY.employee_id` apunta al empleado y no al contrato, a
> diferencia de `ASSIGNMENT`. Motivo: el marcaje es un hecho de la persona en una
> fecha; el contrato vigente en esa fecha se determina por consulta y puede no
> existir (RN-52 lo valida). Acoplar el marcaje al contrato complicaría la
> corrección de datos en el límite entre dos contratos consecutivos.

---

## F.5 Ausencias (`leave`, Fase 6)

```mermaid
erDiagram
    LEAVE_TYPE {
        bigint id PK
        varchar code UK
        varchar name
        bool is_paid
        bool requires_approval
        bool requires_document
        bool allows_negative_balance
        decimal default_annual_days
        smallint min_notice_days
        bool is_active
    }

    LEAVE_ENTITLEMENT {
        bigint id PK
        bigint employee_id FK
        bigint leave_type_id FK
        date period_start
        date period_end
        decimal granted_days
        varchar source "ACCRUAL|MANUAL|CARRYOVER"
    }

    LEAVE_REQUEST {
        bigint id PK
        uuid public_id UK
        bigint employee_id FK
        bigint leave_type_id FK
        date start_date
        date end_date
        decimal requested_days "congelado al solicitar"
        varchar status "DRAFT|SUBMITTED|APPROVED|REJECTED|CANCELLED"
        text reason
        datetime submitted_at "nullable"
    }

    LEAVE_REQUEST_TRANSITION {
        bigint id PK
        bigint leave_request_id FK
        varchar from_status
        varchar to_status
        bigint actor_id FK "nullable"
        varchar actor_repr "snapshot"
        datetime occurred_at
        text note
    }

    LEAVE_LEDGER_ENTRY {
        bigint id PK
        bigint employee_id FK
        bigint leave_type_id FK
        bigint leave_request_id FK "nullable"
        varchar entry_type "ACCRUAL|CONSUMPTION|ADJUSTMENT|EXPIRY|REVERSAL"
        decimal days "signo según entry_type"
        date effective_date
        bigint created_by_id FK "nullable"
    }

    LEAVE_TYPE ||--o{ LEAVE_ENTITLEMENT : "otorga"
    LEAVE_TYPE ||--o{ LEAVE_REQUEST : "clasifica"
    LEAVE_TYPE ||--o{ LEAVE_LEDGER_ENTRY : "contabiliza"
    EMPLOYEE ||--o{ LEAVE_ENTITLEMENT : "acumula"
    EMPLOYEE ||--o{ LEAVE_REQUEST : "solicita"
    EMPLOYEE ||--o{ LEAVE_LEDGER_ENTRY : "registra"
    LEAVE_REQUEST ||--|{ LEAVE_REQUEST_TRANSITION : "transiciona"
    LEAVE_REQUEST ||--o{ LEAVE_LEDGER_ENTRY : "consume"
```

### Máquina de estados de `LEAVE_REQUEST` (RN-45)

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> SUBMITTED : enviar (empleado)
    DRAFT --> CANCELLED : descartar (empleado)
    SUBMITTED --> APPROVED : aprobar (jefe o RRHH, ≠ solicitante)
    SUBMITTED --> REJECTED : rechazar (jefe o RRHH)
    SUBMITTED --> CANCELLED : cancelar (empleado, antes de decidir)
    APPROVED --> CANCELLED : cancelar (RRHH, antes de start_date)
    REJECTED --> [*]
    CANCELLED --> [*]
    APPROVED --> [*]
```

Toda transición produce un `LEAVE_REQUEST_TRANSITION`; las que afectan al saldo
producen además un `LEAVE_LEDGER_ENTRY`. **Ningún otro camino es válido**, y la
implementación rechaza transiciones no declaradas en lugar de asumirlas.

---

## F.6 Documentos y auditoría (`documents` + `audit`)

```mermaid
erDiagram
    DOCUMENT_TYPE {
        bigint id PK
        varchar code UK
        varchar name
        bool is_sensitive
        bool requires_expiry
        smallint retention_years
        json allowed_extensions "política de validación"
        smallint max_size_mb
        bool is_active
    }

    EMPLOYEE_DOCUMENT {
        bigint id PK
        uuid public_id UK
        bigint employee_id FK
        bigint document_type_id FK
        varchar title
        varchar stored_path "UUID generado, NUNCA el nombre del usuario"
        varchar original_filename "solo para mostrar"
        varchar content_type "verificado por magic bytes"
        bigint size_bytes
        char checksum_sha256
        date issued_on "nullable"
        date expires_on "nullable"
        bigint uploaded_by_id FK "nullable"
        datetime uploaded_at
        bool is_active
    }

    AUDIT_EVENT {
        bigint id PK
        datetime occurred_at
        bigint actor_id FK "nullable - SET_NULL"
        varchar actor_repr "snapshot"
        varchar action "catálogo cerrado"
        varchar object_type "app_label.Model"
        varchar object_id "puntero débil"
        varchar object_repr "snapshot"
        varchar outcome "SUCCESS|FAILURE|DENIED"
        varchar ip_address "nullable"
        varchar user_agent "truncado"
        uuid request_id "correlación con logs"
        json metadata "diff filtrado, sin datos sensibles"
    }

    DOCUMENT_TYPE ||--o{ EMPLOYEE_DOCUMENT : "tipifica"
    EMPLOYEE ||--o{ EMPLOYEE_DOCUMENT : "archiva"
    USER ||--o{ EMPLOYEE_DOCUMENT : "sube"
    USER ||--o{ AUDIT_EVENT : "genera"
```

`AUDIT_EVENT` se dibuja deliberadamente **sin** aristas hacia las entidades
auditadas: la referencia es un puntero débil (`object_type` + `object_id`) y no
una FK, para que el evento sobreviva al borrado del objeto
(ver [B.11](02-modelo-relacional.md)).

---

## F.7 Nómina (`payroll`, Fase 8 — anteproyecto)

> **Advertencia:** este diagrama es tentativo. La nómina se diseñará en detalle al
> inicio de la Fase 8, con su propio análisis de dominio. No debe implementarse a
> partir de este esquema.

```mermaid
erDiagram
    PAYROLL_PERIOD {
        bigint id PK
        bigint company_id FK
        varchar code "UK con company_id"
        varchar period_type "MONTHLY|BIWEEKLY"
        date start_date
        date end_date
        varchar status "OPEN|CALCULATING|CLOSED"
    }

    PAYROLL_RUN {
        bigint id PK
        bigint period_id FK
        smallint run_number "UK con period_id"
        varchar status "DRAFT|CALCULATED|APPROVED|PAID|VOID"
        datetime executed_at
        bigint executed_by_id FK
        datetime locked_at "nullable = inmutable"
    }

    PAYROLL_CONCEPT {
        bigint id PK
        varchar code UK
        varchar name
        varchar nature "EARNING|DEDUCTION|EMPLOYER_COST"
        varchar calculation_basis
        bool is_active
    }

    PAYSLIP {
        bigint id PK
        uuid public_id UK
        bigint run_id FK
        bigint employee_id FK
        varchar employee_code_snapshot "redundancia justificada"
        varchar full_name_snapshot "redundancia justificada"
        varchar position_title_snapshot "redundancia justificada"
        varchar department_name_snapshot "redundancia justificada"
        decimal base_salary_snapshot "redundancia justificada"
        decimal gross_total
        decimal deduction_total
        decimal net_total
    }

    PAYSLIP_LINE {
        bigint id PK
        bigint payslip_id FK
        bigint concept_id FK
        decimal quantity
        decimal rate
        decimal amount
        smallint sequence
    }

    PAYROLL_PERIOD ||--o{ PAYROLL_RUN : "se calcula en"
    PAYROLL_RUN ||--o{ PAYSLIP : "produce"
    EMPLOYEE ||--o{ PAYSLIP : "recibe"
    PAYSLIP ||--|{ PAYSLIP_LINE : "detalla"
    PAYROLL_CONCEPT ||--o{ PAYSLIP_LINE : "clasifica"
```

Los campos `*_snapshot` son la aplicación directa de la regla 16 y están
justificados en [§D.7](04-normalizacion.md#d7-redundancia-justificada).

---

## F.8 Mantenimiento del ERD

| Cuándo | Qué hacer |
|---|---|
| Se añade o elimina una entidad | Actualizar F.1 y el diagrama de contexto correspondiente |
| Cambia una cardinalidad | Actualizar ambos diagramas y la tabla A.3 del análisis de dominio |
| Cambia un atributo clave (PK, UK, FK) | Actualizar el diagrama de contexto y el diccionario de datos |
| Cambia un atributo no clave | Basta con actualizar el diccionario de datos |

La revisión de PR debe rechazar una migración que altere relaciones sin
actualizar este documento.
