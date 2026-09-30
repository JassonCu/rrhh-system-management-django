# ADR-009 — Capas `services` y `selectors`, sin repositorios ni inyección de dependencias

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

Hay que decidir **dónde vive la lógica de negocio**, y —más importante— **dónde
se para** la estructura. La regla 38 del encargo advierte contra aplicar patrones
por moda; la 56 prohíbe introducir arquitectura sin justificación.

Tres cosas de este dominio empujan hacia algo más que modelos y vistas:

1. La **autorización a nivel de objeto** debe ocurrir en un solo sitio por
   recurso, o el IDOR es cuestión de tiempo (ADR-005).
2. Los **invariantes entre filas** (no traslape de contratos, suma de FTE, saldo
   de ausencias) necesitan transacción y bloqueo, y no pueden vivir en `save()`.
3. La **auditoría** debe emitirse en la misma transacción que el cambio.

## Alternativas consideradas

### A. *Fat models*: toda la lógica en el modelo
- **A favor:** idiomático en Django; cero módulos nuevos.
- **En contra:** `save()` se ejecuta en contextos donde el caso de uso no aplica
  (cargas de datos, migraciones, `bulk_create` lo salta), y el modelo termina
  necesitando conocer al usuario que actúa para auditar — es decir, la petición.

### B. Lógica en las vistas
- **En contra:** la vista pasa a ser el único sitio donde vive el caso de uso, y
  por tanto solo se puede probar por HTTP. Cada nueva entrada (un comando de
  gestión, una importación) obliga a duplicarla.

### C. `services` + `selectors` *(elegida)*
Dos módulos de **funciones** por app: lecturas acotadas y escrituras
transaccionales.

- **A favor:** el caso de uso es una función invocable desde una vista, un
  comando o una prueba; la autorización tiene un punto único; la auditoría queda
  junto al cambio.
- **En contra:** dos archivos más por app y una convención que sostener.

### D. Repository pattern + inyección de dependencias
- **Rechazada.** El `QuerySet` de Django **ya es** el repositorio. Envolverlo
  añade una capa que hay que mantener, rompe `select_related`/`prefetch_related`
  y obliga a reimplementar la composición de consultas. La inyección de
  dependencias resolvería un problema de acoplamiento que no tenemos: no hay
  intención de cambiar de ORM.

### E. CQRS / Event sourcing
- **Rechazada** por la regla 56: no hay ningún requisito de escala ni de
  reconstrucción temporal que lo justifique.

## Decisión

Se adopta **C**, con un límite explícito.

### Responsabilidades

| Módulo | Sí | No |
|---|---|---|
| `models.py` | Estructura, relaciones, constraints, validaciones **locales a la fila** | Auditar, orquestar otros modelos, conocer permisos |
| `selectors.py` | Lecturas; recibe `user` y devuelve queryset **ya acotado**; aplica `select_related`/`prefetch_related` | Escribir; decidir sobre HTTP |
| `services.py` | Casos de uso de escritura; abre `transaction.atomic()`; valida invariantes entre filas; emite `AuditEvent`; lanza excepciones de dominio | Conocer `HttpRequest`; renderizar; traducir mensajes |
| `views.py` | Traducir HTTP ↔ dominio; permisos; elegir plantilla; mensajes | Contener lógica de negocio |

### Dónde se para

- **No hay repositorios.** Se usa el ORM directamente dentro de los selectores.
- **No hay contenedor de inyección de dependencias.**
- **No hay CQRS, ni event sourcing, ni bus de eventos.**
- **No se escribe un servicio de una línea por simetría.** Un CRUD trivial sin
  invariantes ni auditoría (un `Holiday`, por ejemplo) puede usar el `ModelForm`
  directamente desde la vista. La capa aparece cuando hay algo que proteger, no
  para que todas las apps se parezcan.

### Traducción y errores

Los servicios **no traducen**: lanzan excepciones de dominio con un `code`
estable. La vista lo convierte en mensaje localizado; el log registra el código.
Así el usuario lee su idioma y el incidente sigue siendo buscable.

## Consecuencias

### Positivas
- Los casos de uso se prueban sin cliente HTTP.
- La autorización y la auditoría tienen un lugar predecible.
- Las vistas se mantienen pequeñas y legibles.

### Negativas aceptadas
- Hay que decidir, caso por caso, si una operación merece servicio. El criterio
  («¿hay invariante entre filas, autorización de objeto o auditoría?») es
  explícito, pero sigue siendo un juicio.
- Alguien puede saltarse la capa escribiendo directamente contra el modelo desde
  una vista. Se detecta en revisión, no automáticamente.

### Qué habría que hacer para revertirla
Absorber los servicios en los modelos o en las vistas es mecánico. Añadir
repositorios o DI más adelante también, si aparece una razón — que hoy no existe.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Solo se consume la interfaz pública entre apps (`services`, `selectors`, `constants`, `exceptions`) | `tests/test_app_boundaries.py::test_cross_app_imports_use_the_public_interface` |
| `core` no depende de nadie y `audit` no depende de dominios | `tests/test_app_boundaries.py` |
| Los servicios son atómicos y emiten auditoría | Pruebas de servicio por caso de uso (Fases 3-4) |
| Los selectores devuelven exactamente el alcance esperado por rol | Pruebas de selector (Fase 3) |
| Las vistas no hacen consultas ad-hoc | Revisión de PR |
