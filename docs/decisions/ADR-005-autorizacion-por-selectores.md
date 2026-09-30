# ADR-005 — Autorización a nivel de objeto mediante selectores con alcance

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1 (decisión) · 3 (implementación y verificación)

---

## Contexto

Un sistema de RRHH tiene datos con dueño: un empleado ve **su** expediente, un
jefe ve **su** equipo, RRHH ve todo y un auditor lee sin escribir. Los permisos
de Django responden «¿puede ver expedientes?», no «¿puede ver **este**
expediente?».

La diferencia es el IDOR: si una vista hace `Employee.objects.get(pk=...)` con
un identificador de la URL, cambiar el número da acceso a otro empleado por
mucho que el permiso genérico esté bien concedido.

## Alternativas consideradas

### A. Solo permisos de Django
- **En contra:** no expresan alcance. Habría que comprobar la propiedad del
  objeto en cada vista, a mano, y basta olvidarlo una vez.

### B. `django-guardian` (ACL por fila)
Una tabla de permisos por objeto y usuario.

- **A favor:** máxima granularidad; permisos excepcionales por individuo.
- **En contra:** el alcance de este dominio es **calculable**, no arbitrario: se
  deriva de la jefatura vigente y de las asignaciones. Materializarlo en filas
  obligaría a recalcularlas cada vez que alguien cambia de departamento, cada
  vez que se nombra un jefe y cada vez que entra un empleado — es decir, a
  mantener sincronizada una copia de algo que una consulta ya responde. Añade
  además dos tablas y una dependencia.
- **Costo de revertir:** alto una vez poblada.

### C. Selectores con alcance *(elegida)*
Una función por recurso, `selectors.<recurso>_visible_for(user)`, que devuelve
un queryset **ya acotado**. Toda vista parte de ella.

- **A favor:** un único punto que auditar y probar por recurso; el alcance no
  puede desincronizarse porque no se almacena; funciona igual en listados,
  detalle, edición, exportación y descarga.
- **En contra:** es una convención, no una barrera del framework: una vista que
  no la use se salta la protección.

### D. Middleware o mixin «mágico» que filtre por sí solo
- **Rechazada.** Un filtro implícito es peor que ninguno: cuando falla, falla en
  silencio y nadie sabe dónde mirar.

## Decisión

Se adopta **C**, con tres capas explícitas y en este orden en cada vista:

```
@login_required                                   ¿quién eres?
@permission_required(..., raise_exception=True)   ¿puedes hacer esto?
get_object_or_404(selectors.x_visible_for(user))  ¿sobre este objeto?
```

Detalles que forman parte de la decisión:

- **`raise_exception=True` es obligatorio.** Sin él, un usuario autenticado sin
  permiso es redirigido al login y entra en un bucle en lugar de recibir un 403.
- **Un objeto fuera de alcance devuelve 404, no 403.** Un 403 confirmaría que el
  recurso existe.
- **No hay herencia de alcance.** Poder ver a un empleado no da acceso a su
  salario ni a sus documentos: cada selector aplica su propia regla.
- **El `queryset` de todo `ModelChoiceField` se acota con el selector**, para que
  no se pueda referenciar por POST un objeto que no se puede ver.

## Consecuencias

### Positivas
- La protección contra IDOR vive en un lugar por recurso, y ese lugar se prueba.
- El alcance se deriva de los datos, así que no puede quedar obsoleto.
- Sin dependencias ni tablas adicionales.

### Negativas aceptadas
- Depende de la disciplina: una vista que consulte el modelo directamente elude
  el control. Se compensa con la matriz de pruebas de la Fase 3, que exige una
  fila por vista y rol.
- Un alcance calculado cuesta un `JOIN` frente a una consulta por ACL
  materializada. Los índices I-09 y I-10 del
  [documento de índices](../database/07-integridad-e-indices.md) existen
  exactamente para eso.
- Los permisos excepcionales por individuo («este jefe sí ve salarios») no caben
  en el modelo; se resolverían con un permiso propio, no con una ACL.

### Qué habría que hacer para revertirla
Adoptar `django-guardian` exigiría poblar las ACL de todo el histórico y
mantenerlas con señales. La dirección contraria —abandonar guardian— sería peor.
Por eso la decisión se toma ahora y no después.

## Cómo se verifica

En la Fase 1 no hay recursos con alcance todavía. La verificación se implementa
con la Fase 3 y es condición de cierre de esa fase:

| Verificación | Cuándo |
|---|---|
| Matriz parametrizada `(rol, URL, método, código esperado)` sobre **toda** la tabla de URLs | Fase 3 |
| Un recurso ajeno devuelve **404**, no 403 | Fase 3 |
| `MANAGER` no accede a datos salariales de su equipo | Fase 4 |
| Los `ModelChoiceField` no ofrecen objetos fuera de alcance | Fase 3 |
| Una vista nueva sin fila en la matriz hace fallar la prueba de cobertura de URLs | Fase 3 |
