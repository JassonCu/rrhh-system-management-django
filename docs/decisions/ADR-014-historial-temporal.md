# ADR-014 — Historial temporal frente a columnas mutables

- **Estado:** Aceptado
- **Fecha:** 2026-09-14
- **Decide:** Equipo técnico
- **Fase:** 3 (jefaturas) y 4 (salarios y asignaciones)

---

## Contexto

Tres hechos del dominio **cambian con el tiempo y su pasado importa**:

| Hecho | Quién pregunta por el pasado |
|---|---|
| Quién dirige un departamento | Auditoría: «¿quién aprobó esto en marzo?»; alcance de jefaturas |
| Cuánto cobra alguien | Nómina retroactiva, liquidaciones, indemnizaciones, inspección de trabajo |
| Qué puesto ocupa y en qué área | Antigüedad en el puesto, alcance del jefe, informes históricos |

La forma inmediata de modelarlos es una columna (`Department.head`,
`Employee.salary`, `Employee.position`) que se sobrescribe. Pierde la historia,
y la bitácora de auditoría no la sustituye: por diseño **no guarda importes
salariales** (§G.19) y no está pensada para consultas de negocio.

## Alternativas consideradas

### A. Columnas mutables + auditoría
- **A favor:** esquema mínimo, consultas triviales.
- **En contra:** la historia queda en `AuditEvent`, que no puede tener importes y
  no se consulta con el ORM de forma natural. Una liquidación que necesite el
  salario de hace dos años no tendría de dónde sacarlo.

### B. Tablas de período con vigencia `[desde, hasta]` *(elegida)*
`DepartmentHeadship`, `ContractSalary` y `Assignment`, cada una con fecha de
inicio y fecha de fin opcional (`NULL` = vigente).

- **A favor:** la historia es un dato de primera clase; se consulta «a una
  fecha» con un filtro; nada se sobrescribe.
- **En contra:** más tablas, consultas con condición temporal y reglas de
  continuidad que la base no expresa por completo.

### C. Tablas temporales del motor o paquetes de versionado de filas
(`django-simple-history`, *system-versioned tables*).
- **Rechazada.** Versionan **filas**, no hechos del dominio: registran que cambió
  una columna, no que empezó un nuevo período salarial con su motivo y su
  justificación. Además, las tablas temporales nativas son específicas de motor
  (ADR-003).

## Decisión

Se adopta **B**, con estas reglas comunes:

1. **Nunca se sobrescribe un período.** Un cambio cierra el vigente y abre otro.
2. **Un solo período abierto** donde el dominio lo exige, garantizado por la base
   con índices únicos parciales: `uniq_current_head_per_department`,
   `uniq_open_salary_per_contract`, `uniq_open_primary_assignment`.
3. **Orden de fechas** garantizado por `CheckConstraint`
   (`salary_period_ordered`, `assignment_period_ordered`).
4. **Continuidad y no traslape en servicios.** La base portable no puede impedir
   solapes entre filas (PostgreSQL lo haría con `ExclusionConstraint`; SQLite no,
   ADR-002). Por eso:
   - `set_salary` cierra el salario anterior el **día previo** al nuevo: la
     historia salarial es contigua, sin huecos ni solapes (RN-21).
   - Una asignación principal nueva cierra la anterior el día previo.
   - El primer salario empieza con el contrato.
5. **Contención.** Salarios y asignaciones caen dentro de las fechas del contrato
   (RN-26); al terminar un contrato se cierran en la fecha de baja, y si existe
   un período que **empieza después** de esa fecha, se rechaza la baja en lugar
   de inventar un cierre.

## Consecuencias

### Positivas
- Nómina, liquidaciones e informes pueden reconstruir cualquier fecha pasada.
- El motivo del cambio (`change_reason`, `assignment_reason`) y la justificación
  de salarios fuera de banda viajan con el período, no en un log aparte.
- Los importes quedan bajo `view_salary` y fuera de la bitácora.

### Negativas aceptadas
- Cada lectura del estado actual lleva condición temporal. Se encapsula en
  selectores (`current_salary`, `current_primary_assignment`,
  `employee_ids_assigned_to`) para no repetirla.
- **Condición de carrera en SQLite:** dos cambios salariales simultáneos sobre el
  mismo contrato se serializan con `select_for_update`, que SQLite ignora. La
  última defensa son los índices únicos parciales. En PostgreSQL el bloqueo es
  real.
- Corregir un error de captura en un período ya cerrado no tiene interfaz: se
  hace con un nuevo período y su justificación, o por un procedimiento
  administrativo auditado. Es deliberado.

### Qué habría que hacer para revertirla
Colapsar cada tabla en una columna con el último valor. Es **lossy**: se pierde
toda la historia. No debería revertirse con datos reales.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Solo un salario abierto por contrato, por la base | `test_only_one_open_salary_per_contract` |
| Solo una asignación principal abierta, por la base | `test_only_one_open_primary_assignment` |
| Un aumento cierra el salario anterior el día previo | `test_a_raise_closes_the_previous_salary_the_day_before` |
| Un traslado cierra la asignación anterior el día previo | `test_a_transfer_closes_the_previous_primary_position` |
| La baja cierra salario y asignaciones en la misma fecha | `test_termination_closes_salary_and_positions_on_the_same_day` |
| No se inventan cierres para períodos futuros | `test_termination_refuses_to_rewrite_a_scheduled_raise` |
| Ninguna jefatura vigente duplicada | Pruebas de `departments` sobre `uniq_current_head_per_department` |
