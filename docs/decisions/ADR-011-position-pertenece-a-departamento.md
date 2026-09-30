# ADR-011 — `Position` pertenece a un departamento

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Producto (dominio), con análisis del equipo técnico
- **Fase:** 3
- **Sustituye a:** la propuesta inicial de §D.5.4, que asumía puestos globales

---

## Contexto

El diseño de la Fase 0 modeló `Position` como un catálogo **global** y situó el
departamento en `Assignment`, junto con el puesto. Quedó marcado como decisión
abierta porque **no es una cuestión de gusto**: depende de un hecho del dominio.

La regla es la de cualquier dependencia funcional: `puesto → departamento` debe
cumplirse **para todas las filas**. Un solo contraejemplo la destruye.

### Hechos del dominio confirmados

| Pregunta | Respuesta |
|---|---|
| ¿Existe algún título de puesto ejercible en más de un departamento? | **No.** Cada puesto pertenece por definición a un área |
| ¿Cambia el perfil del puesto según el departamento? | **Sí**, las funciones se definen por área aunque el título coincidiera |
| ¿Se presupuestan plazas por departamento? | **No**, se contrata según necesidad |

La primera respuesta establece que la dependencia funcional **existe**. La
segunda la refuerza: si la descripción del puesto es contenido específico del
área, el puesto no es una entidad transversal ni siquiera conceptualmente. La
tercera descarta la necesidad de una entidad `PlazaPresupuestada`.

## Alternativas consideradas

### A. `Position` como catálogo global
`Position(code, title, job_grade)` sin departamento;
`Assignment(contract, position, department, …)`.

- **A favor:** catálogo compacto; reportería agregada directa por `position_id`;
  un traslado conservando cargo reutiliza la misma fila de puesto.
- **En contra, y decisivo:** **contradice el dominio.** Si ningún título es
  transversal, la DF `position → department` se cumple, y entonces almacenar
  `department_id` en `Assignment` es una **dependencia transitiva**
  (`assignment → position → department`). Su anomalía concreta: nada impediría
  insertar una asignación cuyo `department_id` no coincidiera con el
  departamento del puesto, y la base no lo detectaría. El resultado sería una
  asignación que pertenece a dos departamentos según por dónde se consulte.
- **Costo de revertir:** medio (ver más abajo).

### B. `Position` pertenece a un departamento *(elegida)*
`Position(code, title, job_grade, department)`;
`Assignment(contract, position, …)` **sin** departamento.

- **A favor:** refleja el dominio real; elimina la transitividad; hace imposible
  por construcción la incoherencia entre el departamento de la asignación y el
  del puesto; permite que la descripción del puesto sea específica del área.
- **En contra:** el catálogo de puestos crece con el número de departamentos, y
  la reportería transversal por tipo de cargo se complica (ver Consecuencias).

### C. `Position` global con departamento «sugerido» no autoritativo
- **Rechazada.** Crearía una dependencia parcial ambigua: un dato que a veces
  manda y a veces no. Es el peor de los dos mundos, porque nadie sabría cuál es
  la fuente de verdad.

### D. Entidad `PlazaPresupuestada(departamento, puesto, cantidad, vigencia)`
- **No aplica hoy.** Sería la respuesta correcta si el negocio controlara
  headcount por área, y se confirmó que no. Queda anotada por si cambia: **no se
  resolverá metiendo más datos en `Position`.**

## Decisión

Se adopta **B**. Cambios concretos sobre el diseño de la Fase 0:

### `positions.Position`

```
Position(**id**, _department_id_, _job_grade_id_, code, title, description, is_active)
```

- `department` → `FK(Department, PROTECT)`, **obligatorio**.
- `code` sigue siendo único globalmente: identifica el puesto en toda la
  organización, independientemente de cómo se codifique.
- **Nueva restricción:** `UniqueConstraint(department, title)` — dos puestos con
  el mismo título en el mismo departamento son un error de captura (RN-35). Se
  añade ahora porque **quitar un constraint después es barato y añadirlo es
  caro**: exige limpiar los datos que ya lo violan.

### `contracts.Assignment`

```
Assignment(**id**, _contract_id_, _position_id_, start_date, end_date, is_primary, fte, assignment_reason)
```

- **Se elimina `department_id`.** El departamento se obtiene por
  `assignment.position.department`.
- La clave candidata natural pasa de
  `{contract, position, department, start_date}` a
  `{contract, position, start_date}`.
- `Assignment` ya no tiene **ninguna** referencia redundante: ni `employee_id`
  (transitivo vía contrato) ni `department_id` (transitivo vía puesto).

### Consecuencias en la autorización

El alcance de un `MANAGER` pasa de un `JOIN` a dos:

```
antes:  Assignment.filter(department__in=…, end_date__isnull=True)
ahora:  Assignment.filter(position__department__in=…, end_date__isnull=True)
```

Esto **sustituye el índice I-09**: en lugar de `Assignment(department_id, end_date)`
se necesitan `Position(department_id)` y `Assignment(position_id, end_date)`.
Como la tabla de puestos es pequeña, el coste real es despreciable.

## Consecuencias

### Positivas
- El modelo dice la verdad sobre el dominio.
- Desaparece una dependencia transitiva y con ella su anomalía.
- La descripción del puesto puede ser específica del área, como pide el negocio.
- Es imposible que una asignación contradiga al puesto sobre el departamento.

### Negativas aceptadas
- **El catálogo crece.** Cada departamento necesita sus propias filas de puesto,
  y crear un departamento implica crear sus puestos. Hay que preverlo en el flujo
  de alta y en la carga inicial de datos.
- **La reportería transversal se complica.** «¿Cuántos analistas hay en toda la
  organización?» ya no es un `count()` por `position_id`: exigiría agrupar por
  título en texto, que es justo lo que este proyecto evita.
  **Mitigación documentada, no implementada:** si esa reportería llega a
  requerirse, se añade una taxonomía `JobFamily(code, name)` con
  `Position.job_family_id`, que agrupa puestos equivalentes entre áreas sin
  reintroducir ninguna dependencia. **No se hace ahora** (regla 56).
- **Un traslado entre áreas conservando el cargo** apunta a otra fila de puesto.
  La interfaz debe pedir primero el departamento y luego el puesto; ofrecer un
  selector plano de puestos sería inusable.
- **La comparación salarial entre áreas** por título deja de ser directa. La
  banda sigue viviendo en `JobGrade`, que sí es transversal, así que la
  comparación por grado se mantiene intacta.

### Qué habría que hacer para revertirla
Volver a A exigiría **fusionar** filas de puesto decidiendo cuáles son «el mismo
puesto». Si el perfil o la banda difieren entre áreas —y el negocio confirma que
el perfil difiere—, la fusión es lossy y ambigua. Es la dirección cara, y por eso
esta decisión se toma **antes** de la Fase 3, cuando no hay datos que migrar.

## Cómo se verifica

| Verificación | Cuándo |
|---|---|
| `Position.department` es obligatorio y usa `PROTECT` | Fase 3, prueba de modelo |
| `Assignment` **no** tiene campo `department` | Fase 3, prueba que inspecciona los campos del modelo, como la que ya vigila que `User` no tenga campos de RRHH |
| El título es único dentro del departamento (RN-35) | Fase 3, prueba que espera `IntegrityError` |
| No se puede borrar un departamento con puestos | Fase 3, prueba que espera `ProtectedError` |
| El alcance de `MANAGER` resuelve por `position__department` | Fase 3, pruebas de selector |
| Los índices `Position(department)` y `Assignment(position, end_date)` existen | Fase 3, revisión de la migración |
