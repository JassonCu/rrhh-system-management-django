# ADR-012 — `Employee.employment_status` como estado derivado materializado

- **Estado:** Aceptado
- **Fecha:** 2026-09-14
- **Decide:** Equipo técnico
- **Fase:** 4

---

## Contexto

El estado laboral de una persona (activa, suspendida, dada de baja) **se deriva
de sus contratos**: tiene un contrato `ACTIVE` → está activa; solo uno
`SUSPENDED` → suspendida; solo contratos cerrados → dada de baja, en la fecha de
fin del último. Es una dependencia funcional `{contratos del empleado} →
estado`, así que guardar el estado en `Employee` es, en rigor, **redundancia**.

Y sin embargo el estado se consulta en casi todas partes: listados con filtro,
alcance de jefaturas, desactivación de cuentas, informes, y en fases futuras
asistencia, ausencias y nómina. Derivarlo en cada consulta obliga a una
subconsulta sobre contratos en cada una de ellas.

Además, antes de la Fase 4 **no había contratos**: la Fase 3 necesitaba un
estado laboral y lo modificaba directamente (`terminate_employee`), lo que la
revisión de seguridad de la Fase 3 marcó como H-3.

## Alternativas consideradas

### A. Derivarlo siempre (sin columna)
Anotar el estado con `Subquery`/`Exists` sobre `EmploymentContract`.

- **A favor:** cero redundancia; imposible que diverja.
- **En contra:** cada consulta que filtra por estado arrastra una subconquista
  correlacionada; los selectores de alcance, que ya son el camino caliente, se
  complican; y el estado `ON_LEAVE` (Fase 6) no sale de los contratos, así que
  la derivación tendría que cruzar dos módulos en cada lectura.

### B. Columna materializada con un único escritor *(elegida)*
`Employee.employment_status` y `Employee.termination_date` se guardan, pero
**solo** los escribe `contracts.services._sync_employee_status`, en la misma
transacción que el cambio de contrato que los provoca.

- **A favor:** lecturas triviales e indexables; la regla de derivación vive en
  un único sitio (`contracts.selectors.expected_employment_status`); la
  divergencia es detectable.
- **En contra:** redundancia consciente; exige disciplina (un único escritor) y
  un mecanismo que verifique la invariante.

### C. Columna editable por varios módulos
Cada módulo actualiza el estado cuando le parece.

- **Rechazada.** Es exactamente el defecto H-3: dos caminos de baja que
  terminan divergiendo. Sin un único escritor no hay forma razonable de saber
  cuál tiene razón.

### D. Trigger de base de datos
- **Rechazada** por ADR-003: SQL específico de motor, invisible para el ORM y
  para las pruebas en SQLite.

## Decisión

Se adopta **B**, con tres reglas:

1. **Un único escritor.** `contracts.services._sync_employee_status` es la única
   función que asigna `employment_status`. `employees` ya no tiene caso de uso de
   baja ni expone el campo en formularios.
2. **Misma transacción.** Activar, suspender, reanudar, terminar y vencer un
   contrato sincronizan el estado dentro de su `transaction.atomic`, con las
   filas de contrato y de empleado bloqueadas.
3. **Una invariante verificable.** `contracts.selectors.find_status_inconsistencies`
   recorre la base y compara cada empleado con lo que dicen sus contratos.

**Regla de derivación** (RN-18):

| Contratos fuera de borrador | Estado esperado |
|---|---|
| Alguno `ACTIVE` | `ACTIVE` (o `ON_LEAVE`, que gestionará ausencias) |
| Ninguno activo, alguno `SUSPENDED` | `SUSPENDED` |
| Solo `TERMINATED` / `EXPIRED` | `TERMINATED`, con la fecha de fin del último |
| Ninguno (o solo borradores) | No se deriva: queda como está |

## Consecuencias

### Positivas
- Filtrar por estado es una columna indexada, sin subconsultas.
- Desactivar la cuenta de quien pierde su último vínculo ocurre en el mismo
  acto que la baja (§K).
- La divergencia deja de ser un riesgo silencioso: hay un comando que la
  detecta y una prueba que la ejercita.

### Negativas aceptadas
- **Redundancia.** Una modificación directa por ORM, `shell` o SQL puede
  desincronizar el estado. Se mitiga con el admin de contratos en solo lectura y
  con el comando de verificación, no se elimina.
- **`ON_LEAVE` es compatible con un contrato activo** y la invariante lo tolera:
  la Fase 6 deberá sincronizarlo con el mismo criterio de único escritor.
- **Un empleado sin contratos** conserva su estado inicial (`ACTIVE`). Es el caso
  de las fichas creadas antes de registrar su contrato.

### Qué habría que hacer para revertirla
Pasar a A: sustituir los filtros por anotaciones, retirar las columnas en una
migración y borrar `_sync_employee_status`. Coste medio y sin pérdida de datos,
porque el estado es reconstruible desde los contratos.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Un ciclo de vida completo (alta, suspensión, baja, vencimiento, borrador) deja la base sin inconsistencias | `test_employment_status_stays_consistent_across_the_lifecycle` |
| Una corrupción manual se detecta | `test_the_invariant_detects_a_manual_corruption` |
| `manage.py check_employment_status` falla con inconsistencias | `test_check_command_fails_on_inconsistencies`; ejecutarlo tras cada despliegue y tras `expire_contracts` |
| `employees` no expone el estado en formularios | `test_employee_form_does_not_expose_the_account_link` |
| Nadie más asigna el campo | Revisión de código: `grep -rn "employment_status =" apps/` solo debe devolver `contracts/services.py` |
