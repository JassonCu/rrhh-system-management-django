# ADR-006 — Normalización objetivo: BCNF, con excepciones documentadas

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 0

---

## Contexto

El encargo sitúa la integridad del modelo de datos como prioridad número uno y
pide evaluar formalmente hasta 5NF. Hace falta un criterio explícito: sin él,
cada modelo nuevo se discute desde cero y el resultado depende de quién revise.

## Alternativas consideradas

### A. «3NF es suficiente»
El objetivo habitual de la industria.

- **A favor:** simple de enunciar; cubre la mayoría de las anomalías.
- **En contra:** deja pasar el caso 3NF-pero-no-BCNF (un determinante que no es
  clave candidata), que en entidades asociativas con claves compuestas —de las
  que este modelo tiene muchas— es justo donde aparece.

### B. BCNF como objetivo, con excepciones justificadas *(elegida)*
Toda relación en BCNF; cualquier duplicación exige justificarse por escrito.

### C. Forzar 4NF y 5NF en todo el modelo
- **Rechazada.** Descomponer `Assignment` en proyecciones binarias para «cumplir
  5NF» haría imposible almacenar `fte`, `is_primary` y la vigencia, que dependen
  de la terna completa, y triplicaría las consultas sin eliminar una sola
  redundancia. Normalizar por deporte es tan dañino como no normalizar
  (regla 10 del encargo).

## Decisión

Se adopta **B**, con estas reglas de gobierno:

1. **Toda relación en BCNF.** Se verifica que el conjunto de determinantes
   coincide con el de claves candidatas; el análisis se hace contra las **claves
   naturales**, no contra la clave sustituta (que haría trivial cualquier
   comprobación).
2. **4NF por separación de hechos independientes.** Teléfonos, direcciones,
   documentos y contactos de emergencia viven en relaciones distintas
   precisamente para no generar productos cartesianos.
3. **5NF se evalúa y se descarta con argumento.** En `Assignment` no existe la
   restricción cíclica que obligaría a descomponer: que un departamento tenga
   plazas de un puesto y que un empleado esté en ese departamento **no implica**
   que las ocupe.
4. **Nada derivable se almacena**, salvo excepción documentada. Sin
   `full_name`, sin `balance`, sin `worked_minutes`, sin `department_name`.
5. **Toda excepción entra en la tabla de §D.7** y debe cumplir tres condiciones:
   representar un hecho **fechado e inmutable**, estar documentada, y tener una
   prueba que verifique que el snapshot **no** cambia cuando cambia el origen.
6. **Los conjuntos cerrados llevan `CheckConstraint`**, no solo `choices`:
   `choices` no se valida en `create()`, `update()` ni `bulk_create()`.

Excepciones aprobadas al escribir este ADR: los `*_snapshot` de `Payslip`, el
`actor_repr`/`object_repr` de la auditoría, `LeaveRequest.requested_days` y
—como caso límite, con su propio ADR-012— `Employee.employment_status`.

## Consecuencias

### Positivas
- Las anomalías de inserción, actualización y borrado quedan analizadas una por
  una, con el escenario concreto que cada decisión evita.
- Hay un criterio objetivo en la revisión de PR: o la relación está en BCNF, o
  hay una entrada en la tabla de excepciones.

### Negativas aceptadas
- Más tablas y más `JOIN`. Consultar «departamento actual del empleado X» cruza
  `Employee → EmploymentContract → Assignment → Department`. Se compensa con
  índices justificados y con `select_related` en los selectores.
- Modelar cuesta más por adelantado que escribir un CRUD. Es el intercambio
  explícito del proyecto.

### Qué habría que hacer para revertirla
Desnormalizar por rendimiento es posible **después de medir**, y entraría por la
tabla de excepciones con su justificación y su prueba. Lo que no se admite es
desnormalizar por comodidad al escribir.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| El análisis por entidad existe y está al día | [Dependencias funcionales](../database/03-dependencias-funcionales.md) y [Normalización](../database/04-normalizacion.md) |
| Cada constraint declarado se cumple en la base | Pruebas de modelo que esperan `IntegrityError` |
| Los conjuntos cerrados tienen `CheckConstraint` además de `choices` | Pruebas de modelo por entidad |
| Las excepciones no derivan con el tiempo | Prueba de snapshot por excepción (Fases 4 y 8) |
| El ERD refleja el modelo real | Revisión de PR: una migración que cambie relaciones sin actualizar el ERD se rechaza |
