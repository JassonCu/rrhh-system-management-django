# ADR-010 — Entidad `Company` desde el inicio

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Producto, con recomendación del equipo técnico
- **Fase:** 1

---

## Contexto

El supuesto S-02 del análisis de dominio asumía **una sola entidad legal**. La
pregunta era si modelarla explícitamente o dejarla implícita.

Es una decisión con **coste asimétrico**: barata hoy, cara después. No se trata
de anticipar un requisito, sino de reconocer que este cambio concreto, hecho
tarde, no es una migración de esquema sino una migración de datos con riesgo.

## Alternativas consideradas

### A. Empresa implícita (no modelarla)
Los departamentos y contratos existen sin referencia a una entidad legal.

- **A favor:** una tabla menos y dos FK menos; el modelo arranca más simple.
- **En contra:** si mañana aparece una segunda entidad legal —una filial, una
  escisión, una empresa de servicios que factura a la matriz— hay que:
  1. añadir una FK **no nula** a tablas con datos ya cargados, lo que exige una
     migración en tres pasos (nula → poblar → no nula);
  2. reescribir todas las restricciones de unicidad, porque `Department.code`
     pasa de único global a único **por empresa**, y lo mismo para los catálogos;
  3. revisar cada selector de autorización, porque el alcance deja de ser «toda
     la organización» y pasa a estar delimitado por empresa;
  4. decidir qué hacer con el histórico, que no dice a qué empresa pertenecía.
- **Costo de revertir:** alto, y creciente con el volumen de datos.

### B. Modelar `Company` desde el inicio *(elegida)*
Una tabla con una sola fila en la práctica, referenciada solo por `Department`,
`EmploymentContract` y `Holiday`.

- **A favor:** el día que aparezca una segunda entidad legal es un alta de fila,
  no una migración. Las unicidades ya están planteadas por empresa donde
  corresponde.
- **En contra:** una tabla y tres FK que hoy no aportan nada visible; un `JOIN`
  más en algunas consultas; hay que crear la fila inicial.

### C. Multi-empresa completo (tenancy)
Aislamiento por esquema o filtrado transversal obligatorio en cada consulta.

- **Rechazada.** Eso sí sería anticipar un requisito inexistente, con un coste
  permanente en cada consulta y en cada prueba.

## Decisión

Se adopta **B**, con alcance deliberadamente mínimo:

- `Company` es referenciada **solo** por `Department`, `EmploymentContract` y
  `Holiday`. No se propaga a `Employee`, `Position` ni `JobGrade`: una persona y
  un catálogo de puestos pueden ser compartidos; lo que pertenece a una entidad
  legal es el **contrato** y la **estructura organizacional**.
- `Department.code` es único **por empresa**, no global. Es la restricción que
  más caro saldría cambiar después.
- Todas las FK hacia `Company` usan `PROTECT`: borrar la empresa no puede vaciar
  el organigrama ni la historia laboral.
- **No** se implementa filtrado por empresa en los selectores todavía. Si algún
  día hay más de una, ese es el trabajo que quedará pendiente — y será acotado,
  porque el dato ya estará en su sitio.

## Consecuencias

### Positivas
- La evolución multi-empresa es un cambio de datos y de selectores, no de
  esquema sobre tablas pobladas.
- El modelo dice la verdad: los contratos se firman con una persona jurídica.

### Negativas aceptadas
- Complejidad que hoy no se usa: una tabla, tres FK y un `JOIN` ocasional.
- Hay que sembrar la fila inicial en cualquier entorno nuevo, lo que añade un
  paso a la puesta en marcha.
- Si el negocio confirma que jamás habrá una segunda entidad legal, esto habrá
  sido trabajo inútil — modesto, pero inútil.

### Qué habría que hacer para revertirla
Eliminarla **antes de la Fase 3** cuesta prácticamente cero: una migración que
borra la tabla y tres FK, sin datos reales que preservar. Después de cargar
empleados y contratos, el coste crece con el volumen. Ese es justamente el
argumento para decidirlo ahora.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| `Company` existe con sus unicidades (`code`, `tax_id`) | `apps/core/tests/test_models.py::test_company_code_is_unique`, `...::test_company_tax_id_is_unique` |
| No se puede borrar una empresa referenciada | `...::test_company_cannot_be_deleted_while_referenced` |
| `Holiday` es único por empresa y fecha | `...::test_holiday_is_unique_per_company_and_date` |
| El código de país se valida | `...::test_invalid_country_code_is_rejected` |
| `Department.code` es único **por empresa** | Fase 3 |
