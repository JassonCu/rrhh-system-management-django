# D. Normalización · E. Anomalías

Objetivo declarado del proyecto: **no** una base de datos "que funcione", sino una
sin redundancia innecesaria ni anomalías. Este documento demuestra el grado de
normalización alcanzado, entidad por entidad, y documenta cada excepción.

**Resultado global: todas las relaciones están en BCNF.** Las excepciones
aparentes (snapshots históricos) se analizan en §D.7 y se justifican como hechos
temporales, no como redundancia.

---

## D.1 Método

Para cada relación se verificó, en este orden:

1. **1NF** — atomicidad de atributos, ausencia de grupos repetitivos y de listas
   embebidas en cadenas o JSON.
2. **2NF** — 1NF + ningún atributo no primo depende **parcialmente** de una clave
   candidata compuesta.
3. **3NF** — 2NF + ningún atributo no primo depende **transitivamente** de una
   clave candidata.
4. **BCNF** — todo determinante es clave candidata.
5. **4NF** — BCNF + ausencia de dependencias multivaluadas no triviales.
6. **5NF** — 4NF + ausencia de dependencias de reunión no implicadas por las claves.

Las dependencias funcionales que sustentan el análisis están en
[Dependencias funcionales](03-dependencias-funcionales.md).

---

## D.2 Observación previa: la clave sustituta no normaliza sola

Como todas las relaciones tienen PK sustituta `id`, la dependencia `id → resto`
existe siempre y, tomada aisladamente, "demostraría" 2NF y 3NF de forma trivial.
Eso sería un autoengaño.

El análisis correcto se hace sobre las **claves candidatas naturales**. Ejemplo:
`Assignment` tiene la candidata compuesta
`{contract_id, position_id, start_date}`; es contra **esa** clave —y no contra
`id`— contra la que hay que verificar dependencias parciales y transitivas. Todo
el análisis siguiente sigue ese criterio.

---

## D.3 Primera Forma Normal (1NF)

**Se cumple en todas las relaciones.** Puntos donde el diseño se apartó
deliberadamente de la solución "cómoda":

| Tentación descartada | Solución adoptada | Motivo |
|---|---|---|
| `Person.phones = "5551111,5552222"` | Relación `ContactMethod` | Un valor no atómico impide indexar, buscar, validar unicidad y marcar un principal. Además obliga a parsear en Python, donde nada garantiza el formato |
| `Person.dpi`, `Person.nit`, `Person.passport` | Relación `IdentityDocument` | Son un grupo repetitivo por columnas. Cada nuevo tipo exigiría una migración de esquema y la tabla se llenaría de nulos |
| `WorkSchedule.monday_start … sunday_end` (14 columnas) | Relación `WorkScheduleDay` | Grupo repetitivo clásico. Con la tabla, consultar "¿trabaja el sábado?" es un `filter`, no un `OR` de siete columnas |
| `Employee.skills = ["python","sql"]` (JSON) | No se modela (fuera de alcance, A.6). Si se requiere: `Skill` + `EmployeeSkill` | Una lista JSON no permite renombrar una competencia en un solo lugar, ni contar cuántos empleados la tienen sin escanear la tabla |
| `Department.employee_ids` (JSON) | Relación `Assignment` | Sería una relación oculta en un campo, sin integridad referencial |

**Uso de JSON permitido y su justificación** (regla 7). Solo dos campos:

| Campo | ¿Por qué es legítimo? |
|---|---|
| `AuditEvent.metadata` | Contenido genuinamente semiestructurado: el diff varía por tipo de objeto. No se une con otras tablas, no se filtra relacionalmente, no representa una relación del dominio. Es una carga útil de un hecho |
| `DocumentType.allowed_extensions` | Lista de configuración corta y cerrada, consumida por un validador. No es una entidad del dominio: nadie consultará "qué tipos de documento aceptan PDF" como requisito de negocio. Alternativa igualmente aceptable: `CharField` con valores separados por coma |

Cualquier otro uso de JSON debe justificarse en un ADR.

---

## D.4 Segunda Forma Normal (2NF)

Solo es evaluable de forma no trivial en las relaciones con **clave candidata
compuesta**. Estas son:

| Relación | Clave candidata compuesta | Atributos no primos | ¿Dependencia parcial? |
|---|---|---|---|
| `IdentityDocument` | `{document_type, number, issuing_country}` | `person_id`, `issued_on`, `expires_on`, `is_primary` | **No.** Ningún atributo depende solo de `number`, ni solo de `document_type` |
| `ContactMethod` | `{person_id, contact_type, value}` | `is_primary`, `notes` | **No.** `is_primary` depende del trío completo |
| `DepartmentHeadship` | `{department_id, start_date}` | `employee_id`, `end_date` | **No.** `employee_id` no depende solo del departamento (cambia con el tiempo) ni solo de la fecha |
| `ContractSalary` | `{contract_id, effective_from}` | `amount`, `currency`, `pay_frequency` | **No.** `amount` depende del par completo; ese es exactamente el punto del historial |
| `Assignment` | `{contract_id, position_id, start_date}` | `end_date`, `is_primary`, `fte` | **Ver análisis abajo** |
| `WorkScheduleDay` | `{work_schedule_id, weekday}` | `start_time`, `end_time`, `break_minutes` | **No** |
| `AttendanceEntry` | `{employee_id, work_date, check_in_at}` | `check_out_at`, `source` | **No** |
| `LeaveEntitlement` | `{employee_id, leave_type_id, period_start}` | `period_end`, `granted_days` | **Analizado abajo** |
| `Holiday` | `{company_id, date}` | `name`, `is_mandatory` | **No** |

### Análisis: `Assignment`

Los atributos no primos son `end_date`, `is_primary` y `fte`. Ninguno depende de
un subconjunto propio de la clave:

- `fte` **no** depende de `{position_id}`: el mismo puesto puede ejercerse a
  tiempo completo o parcial según el contrato.
- `is_primary` **no** depende de `{contract_id}` sola: un contrato puede tener
  varias asignaciones y solo una es principal *en cada momento*.
- `end_date` **no** depende de `{contract_id, start_date}` sin el puesto: dos
  asignaciones distintas iniciadas el mismo día pueden terminar en fechas
  distintas.

→ **2NF cumplida.**

### Análisis: `LeaveEntitlement`

`period_end` depende de `{leave_type_id, period_start}` (el período es anual y su
duración la define el tipo) pero **no** de `employee_id`. ¿Es una dependencia
parcial?

Estrictamente, si el negocio garantiza que el período depende solo del tipo y la
fecha de inicio, sí lo es. La descomposición pura sería extraer una relación
`LeavePeriod(**leave_type_id, period_start**, period_end)`.

**Decisión: no se descompone**, por dos razones de dominio: (a) en Guatemala el
período de vacaciones se cuenta **desde el aniversario de ingreso de cada
empleado**, por lo que `period_start` y `period_end` sí dependen del empleado;
(b) los tipos con período fijo (año calendario) y con período móvil (aniversario)
coexisten, de modo que la DF `{tipo, inicio} → fin` no se sostiene como
restricción universal.

→ **2NF cumplida**, con la salvedad documentada. Si el negocio confirma que todos
los períodos son de año calendario, deberá revisarse.

---

## D.5 Tercera Forma Normal (3NF)

Es la forma normal donde este diseño toma sus decisiones más caras. Se documentan
las **cuatro** transitividades eliminadas y una vigilada.

### D.5.1 Eliminada: `Employee → Department → nombre del departamento`

El modelo ingenuo que el enunciado prohíbe (regla 9):

```
Employee(id, department_id, department_name, department_manager)   ← INCORRECTO
```

Dependencia transitiva: `employee_id → department_id → department_name`.

**Solución adoptada — más fuerte que la del enunciado.** No solo se elimina
`department_name`: se elimina también `department_id` de `Employee`, porque la
pertenencia a un departamento **tiene vigencia** y por tanto no es un atributo del
empleado sino un hecho fechado:

```
Employee(id, person_id, employee_code, hire_date, employment_status)
Assignment(id, contract_id, position_id, start_date, end_date, is_primary, fte)
Position(id, department_id, job_grade_id, code, title)
Department(id, company_id, code, name, cost_center)
```

El nombre del departamento vive **solo** en `Department`, que es su fuente de
verdad. La consulta "departamento actual del empleado" recorre
`Employee → EmploymentContract → Assignment → Position → Department` con filtro
`end_date IS NULL`, resuelta en un `selector` con `select_related`.

### D.5.2 Eliminada: `Position → JobGrade → rango salarial`

```
Position(id, code, title, min_salary, max_salary)      ← INCORRECTO
```

Dependencia transitiva `position_id → job_grade → min_salary`. Un ajuste de banda
salarial obligaría a actualizar todos los puestos del grado, con riesgo de dejar
valores inconsistentes. Solución: `JobGrade` como entidad propia y
`Position.job_grade_id` como única referencia.

### D.5.3 Eliminada: `Assignment → Contract → Employee`

```
Assignment(id, contract_id, employee_id, position_id, ...)          ← INCORRECTO
```

Dependencia transitiva `assignment_id → contract_id → employee_id`. Su anomalía
concreta: nada impide insertar una asignación cuyo `employee_id` no coincida con
`contract.employee_id`, produciendo una asignación que pertenece a dos empleados
distintos según por dónde se consulte. Se elimina el atributo.

**Costo aceptado:** las consultas por empleado requieren un join adicional
(`contract__employee`), mitigado con un índice sobre `Assignment.contract_id` y
`EmploymentContract.employee_id`.

### D.5.4 Eliminada: `Assignment → Position → Department`

Esta fue la bifurcación de diseño más importante del modelo organizacional, y
**la resolvió un hecho del dominio, no una preferencia**.

La pregunta era si se cumple `position_id → department_id`. Una dependencia
funcional debe valer **para todas las filas**: basta un título de puesto
ejercible en dos departamentos para que no exista.

El negocio confirmó que **ningún título es transversal** y que **el perfil del
puesto se define por área**. Por tanto la DF existe, y con ella la cadena
`assignment_id → position_id → department_id`. El modelo correcto es:

```
Position(id, department_id, job_grade_id, code, title, description)   ← el puesto es de un área
Assignment(id, contract_id, position_id, start_date, end_date, …)     ← SIN department_id
```

Almacenar `department_id` en `Assignment` permitiría registrar una asignación
cuyo departamento no coincidiera con el del puesto, sin que la base lo impidiera:
una asignación que pertenece a dos departamentos según por dónde se consulte.

**Si la respuesta del negocio hubiera sido la contraria** —aunque fuese un solo
puesto transversal—, la DF no existiría y `department_id` **sería obligatorio**
en `Assignment`, porque derivarlo del puesto perdería información. El mismo
modelo es correcto o incorrecto según un hecho del mundo, y por eso la decisión
se documenta en [ADR-011](../decisions/ADR-011-position-pertenece-a-departamento.md)
junto con las preguntas que la determinaron.

**Costo aceptado:** el catálogo de puestos crece con el número de departamentos,
y la reportería transversal por tipo de cargo exigiría agrupar por título. La
salida documentada, si llega a hacer falta, es una taxonomía `JobFamily`
referenciada desde `Position` — no reintroducir el departamento en `Assignment`.

### D.5.5 Vigilada: `Address.postal_code → locality, region`

Ver [§C.4](03-dependencias-funcionales.md#c4-employees). Sin catálogo geográfico,
la dependencia no es una restricción del dominio y la relación permanece en 3NF.
Se registra como deuda: introducir el catálogo obliga a extraer `PostalCode`.

---

## D.6 BCNF, 4NF y 5NF

### BCNF

**Todas las relaciones están en BCNF.** Verificación: en cada relación, el
conjunto de determinantes coincide con el conjunto de claves candidatas (ver la
tabla resumen de [§C.11](03-dependencias-funcionales.md#c11-resumen)).

El caso típico de 3NF-pero-no-BCNF (dos claves candidatas compuestas solapadas con
un determinante no candidato) **no se presenta** porque las relaciones asociativas
del modelo tienen una única clave natural compuesta y todos los atributos no
primos dependen de ella completa.

### 4NF — dependencias multivaluadas

Una DMV no trivial aparece cuando una relación mezcla **dos hechos multivaluados
independientes** sobre la misma clave. Se auditaron los candidatos:

| Candidato | ¿Hay DMV? | Resolución |
|---|---|---|
| Persona → teléfonos **y** direcciones | Sí, son independientes | Ya están en relaciones **separadas** (`ContactMethod`, `Address`). Una tabla `PersonContactInfo(person, phone, address)` produciría el producto cartesiano clásico: 3 teléfonos × 2 direcciones = 6 filas para 5 hechos. **4NF cumplida por construcción** |
| Persona → documentos **y** contactos de emergencia | Sí, independientes | Relaciones separadas. **4NF cumplida** |
| Empleado → puestos (en `Assignment`) | **No** | Analizado abajo |
| Empleado → ausencias **y** marcajes | Sí, independientes | Relaciones separadas |

**Análisis de `Assignment`.** Tras ADR-011 la relación es binaria en su parte
clave —`(contract, position)` más la vigencia— y el departamento ya no aparece.
La pregunta de 4NF se simplifica: ¿hay dos hechos multivaluados **independientes**
sobre el contrato? No. El único hecho multivaluado es «qué puestos ocupa este
contrato y desde cuándo», y cada fila lleva atributos propios (`fte`,
`is_primary`, vigencia) que dependen de la combinación completa.

→ **No hay DMV. 4NF cumplida.**

*(Escenario matricial: si un empleado reparte su jornada entre dos áreas, ocupa
dos puestos —uno de cada área, por ADR-011— y se registran dos asignaciones con
FTE 0.5 cada una. La 4NF se mantiene.)*

### 5NF — dependencias de reunión

Una violación de 5NF exige una relación n-aria (n ≥ 3) descomponible sin pérdida
en tres o más proyecciones, con una restricción cíclica del dominio que las
vuelva a reunir sin generar tuplas falsas.

Tras ADR-011 **no queda ninguna relación ternaria en el modelo**: la única
candidata real, `Assignment(contract, position, department)`, pasó a ser
`Assignment(contract, position, …)` al eliminarse la columna transitiva. Las
demás asociativas (`ContractSalary`, `DepartmentHeadship`, `LeaveEntitlement`)
son binarias más vigencia.

→ **No hay dependencia de reunión. 5NF cumplida trivialmente**, sin descomponer
nada.

**Se declara explícitamente que no se forzará 5NF** (regla 10): descomponer una
asociativa en proyecciones binarias haría imposible almacenar `fte`,
`is_primary` y la vigencia —que dependen de la combinación completa— y
multiplicaría las consultas sin eliminar una sola redundancia. **BCNF es
suficiente y correcto para este modelo, y 4NF se cumple por la separación de
hechos independientes.**

---

## D.7 Redundancia justificada

Cuatro casos de duplicación deliberada. Cada uno cumple el mismo criterio: **el
valor almacenado es un hecho fechado, no una copia del dato vivo.** Un hecho
histórico no tiene "fuente de verdad" externa que pueda desincronizarse, porque su
valor no vuelve a cambiar.

| # | Caso | Qué se duplica | Por qué NO es una violación |
|---|---|---|---|
| 1 | `Payslip.*_snapshot` | Nombre, puesto, departamento y salario del empleado | Un recibo es un documento legal inmutable. Debe mostrar el puesto vigente **ese mes**. Si se derivara por join, reimprimir un recibo de 2024 mostraría datos de 2026: falsificación documental, no normalización |
| 2 | `AuditEvent.actor_repr` / `object_repr` | Representación textual del actor y del objeto | El evento debe seguir siendo legible tras el borrado del objeto. La DF real es `{actor_id, occurred_at} → actor_repr` |
| 3 | `LeaveRequest.requested_days` | Días hábiles calculados | Depende de la jornada y del calendario de feriados *vigentes al solicitar*. Un feriado decretado después no debe alterar solicitudes ya aprobadas |
| 4 | `LeaveRequestTransition.actor_repr` | Quién decidió | Igual que (2) |

**Regla de gobierno:** cualquier nueva duplicación debe (a) representar un hecho
fechado e inmutable, (b) documentarse en esta tabla, y (c) tener un test que
verifique que el snapshot **no** cambia cuando cambia el dato de origen.

### Caso límite documentado: `Employee.employment_status`

Es estado **corriente**, no histórico, y es derivable de los contratos. No encaja
en la tabla anterior. Se conserva por tres razones:

1. Es el punto de anclaje de las transiciones de ciclo de vida y de los permisos
   (un empleado `TERMINATED` no puede autenticarse ni solicitar ausencias).
2. Filtrar la lista principal de empleados por estado sin esta columna exige un
   `EXISTS` correlacionado sobre contratos en cada consulta.
3. No es una **dependencia transitiva**: depende de `employee_id`, no de otro
   atributo no primo. Formalmente el modelo sigue en 3NF/BCNF.

**Mitigación obligatoria:** la columna se modifica **exclusivamente** desde
`contracts.services`, en la misma transacción que altera el contrato, y existe un
test de invariante (RN-18) que recorre la base y verifica la coherencia entre
`employment_status` y el estado real de los contratos. Se documenta como
**ADR-012**.

---

# E. Anomalías

Para cada tipo de anomalía se muestra el escenario concreto que la produciría en
un modelo ingenuo y el mecanismo por el que este diseño la impide.

## E.1 Anomalías de inserción

| Escenario | Modelo ingenuo | Este modelo |
|---|---|---|
| Crear un departamento nuevo antes de asignarle personal | Imposible si el departamento vive como columna de `Employee`: no hay dónde insertarlo sin inventar un empleado ficticio | `Department` es una entidad propia; se inserta sin dependencias |
| Registrar un puesto vacante | Imposible si el puesto es un texto en `Employee` | `Position` es un catálogo independiente |
| Dar de alta a una persona antes de firmar su contrato | Imposible si el salario y la fecha de contrato son columnas obligatorias de `Employee` | `Person` → `Employee` → `EmploymentContract` son tres pasos independientes; el contrato admite estado `DRAFT` |
| Registrar el segundo teléfono de una persona | Requiere alterar el esquema (añadir `phone2`) o concatenar | `INSERT` en `ContactMethod` |
| Crear un tipo de ausencia que nadie ha solicitado aún | Imposible si el tipo es un string en la solicitud | `LeaveType` es catálogo |

## E.2 Anomalías de actualización

| Escenario | Modelo ingenuo | Este modelo |
|---|---|---|
| Renombrar "Recursos Humanos" a "Gestión de Personas" | `UPDATE` masivo sobre todas las filas de `Employee` que copian el nombre; si una falla, coexisten dos nombres | Una fila en `Department`. Cero riesgo |
| Ajustar el rango de la banda salarial G5 | `UPDATE` sobre N puestos, con posibilidad de dejarlos inconsistentes | Una fila en `JobGrade` |
| Registrar un aumento de salario | Sobrescribe el salario anterior: **se pierde la historia** y la nómina pasada deja de ser reproducible | `INSERT` en `ContractSalary`; el registro anterior se cierra con `effective_to` |
| Corregir un apellido mal escrito | Hay que actualizarlo en `Person`, en `User`, en cada recibo y en cada registro de auditoría | Solo en `Person`. Recibos y auditoría conservan el snapshot **por diseño** (§D.7) |
| Cancelar una ausencia aprobada | Un campo `taken_days` mutable queda desincronizado si alguna ruta del código olvida decrementarlo | `INSERT` de un asiento `REVERSAL` en el ledger. El saldo se recalcula solo |
| Cambiar de jefe a un departamento | Sobrescribe `manager_id`: se pierde quién aprobaba antes | `INSERT` en `DepartmentHeadship` y cierre del período anterior |

## E.3 Anomalías de eliminación

| Escenario | Modelo ingenuo | Este modelo |
|---|---|---|
| Dar de baja al último empleado de un departamento | Desaparece la existencia del departamento | `Department` persiste; se marca `is_active = False` |
| Eliminar un departamento | `CASCADE` arrastra empleados, asignaciones y su historia | `PROTECT`: la operación se rechaza mientras existan asignaciones |
| Eliminar un puesto | Se pierde el título de puesto de todos los recibos históricos | `PROTECT` + snapshot en `Payslip` |
| Eliminar un departamento con puestos definidos | Se perderían las definiciones de puesto del área | `PROTECT` desde `Position`; el departamento se desactiva |
| Eliminar un usuario del sistema | `CASCADE` borraría su rastro de auditoría — **exactamente lo que buscaría un atacante** | `AuditEvent.actor_id` con `SET_NULL` + `actor_repr` conservado. El evento sobrevive |
| Eliminar un empleado | Desaparecen contratos, nómina y expediente legal | `PROTECT` en toda la cadena. La baja es `employment_status = TERMINATED`, nunca un `DELETE` |
| Borrar una solicitud de ausencia rechazada | Se pierde la evidencia de la decisión | Estado `REJECTED` + transiciones append-only |

## E.4 Anomalías que el modelo **no** puede evitar por sí solo

Honestidad de diseño: hay reglas que ningún constraint declarativo portable puede
garantizar. Se enumeran para que quede explícito **dónde** se hace cumplir cada
una y **cómo** se verifica.

| Regla | Por qué no es declarativa | Dónde se aplica | Cómo se verifica |
|---|---|---|---|
| RN-14 no traslape de contratos | Requiere comparar rangos entre filas. PostgreSQL lo resolvería con `EXCLUDE USING gist`; SQLite no lo soporta | `contracts.services`, bajo transacción con `select_for_update` | Test de traslape en cada frontera (antes, dentro, después, exacto) |
| RN-21 continuidad salarial | Íbid | `contracts.services` | Test de historial sin huecos |
| RN-25 suma de FTE ≤ 1 | Agregación entre filas | `contracts.services` | Test paramétrico |
| RN-26 asignación contenida en el contrato | Requiere leer la fila padre | `contracts.services` | Test de frontera |
| RN-31 aciclicidad del organigrama | Requiere recursión | `departments.services` | Test de ciclo directo e indirecto |
| RN-41 no traslape de ausencias | Comparación entre filas | `leave.services` | Test de traslape |
| RN-43 saldo no negativo | Agregación sobre el ledger | `leave.services` | Test de saldo insuficiente |
| RN-44 aprobador ≠ solicitante | Involucra al usuario de la petición | `leave.services` + capa de permisos | Test de autoaprobación (también es un test de seguridad) |

**Compromiso:** al migrar a PostgreSQL (ADR-003), las reglas de no traslape se
promoverán a `ExclusionConstraint` con `daterange` y `btree_gist`, quedando la
validación en servicio como defensa en profundidad y como fuente de mensajes de
error legibles.
