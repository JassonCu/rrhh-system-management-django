# ADR-015 — Libro de ausencias (ledger) en lugar de un campo `balance`

- **Estado:** Aceptado
- **Fecha:** 2026-09-18
- **Decide:** Equipo técnico
- **Fase:** 6

---

## Contexto

Un saldo de vacaciones cambia por muchas causas: el devengo de cada mes, cada
ausencia aprobada, cada cancelación, cada corrección de RRHH. La pregunta que
más se le hace a RRHH no es «¿cuánto tengo?», sino **«¿por qué tengo eso?»**.

La forma obvia —una columna `balance` que se suma y se resta— responde a la
primera pregunta y destruye la respuesta a la segunda.

## Decisión

El saldo **no se almacena**. Se calcula como `SUM(days)` sobre
`LeaveLedgerEntry`, un libro **append-only**:

| Asiento | Signo | Nace de |
|---|---|---|
| `ACCRUAL` | positivo | el devengo mensual (`accrue_leave`) |
| `CONSUMPTION` | negativo | una solicitud aprobada |
| `REVERSAL` | positivo | la cancelación de una solicitud aprobada |
| `ADJUSTMENT` | cualquiera | una corrección manual de RRHH, con motivo obligatorio |

Un error **nunca se corrige editando o borrando** un asiento: se escribe otro.

### Cómo se hace cumplir

No basta con prometerlo en un comentario:

1. `LeaveLedgerEntry.save()` rechaza actualizar una fila existente, y `delete()`
   rechaza borrarla, con `LedgerImmutableError`.
2. Un `QuerySet` propio bloquea `update()` y `delete()` masivos, que saltarían
   la guarda del modelo. Es el mismo patrón que la bitácora (ADR-008).
3. El modelo solo declara permisos `add` y `view`: no existe
   `change_leaveledgerentry` ni `delete_leaveledgerentry` para otorgar.
4. La base de datos exige `days <> 0`, que **el signo coincida con el tipo** de
   asiento y que todo consumo o reversa apunte a su solicitud.
5. Las claves foráneas son `PROTECT`: borrar una solicitud o un tipo con asientos
   falla.

## Alternativas descartadas

- **Columna `balance` en `LeaveEntitlement`.** Simple y rápida de leer, pero
  diverge del detalle a la primera escritura concurrente o al primer arreglo
  manual por SQL, y entonces nadie sabe cuál de los dos es el correcto.
- **Columna `balance` más el libro.** Es la anterior con más código: dos
  fuentes de verdad que hay que mantener sincronizadas. Si el volumen lo exige
  algún día, se materializará **después de medir**, con un único escritor, como
  `employment_status` (ADR-012).

## Consecuencias

### Positivas
- Cada saldo se explica asiento por asiento, con quién y por qué.
- Cancelar una ausencia aprobada devuelve los días sin reescribir el pasado: el
  consumo y su reversa quedan a la vista.
- Una auditoría externa puede reconstruir cualquier saldo a cualquier fecha.

### Negativas aceptadas
- **Leer un saldo es una agregación**, no una lectura de columna. Con el índice
  `(employee, leave_type)` es barata al volumen previsto.
- **Aprobar exige serializar.** Dos aprobaciones simultáneas contra el mismo
  saldo podrían pasar ambas el chequeo de RN-43. Los servicios bloquean las
  solicitudes de la persona (`_lock_requests_of`) antes de leer el saldo.
- **Los asientos de ajuste no se deshacen**: se compensan con el contrario, y
  ambos quedan. Es exactamente lo que se busca.

## Pendiente

- **Caducidad (`EXPIRY`)**: el diseño de la Fase 0 la preveía; ninguna política
  la exige hoy. Si llega, es un tipo de asiento nuevo y un comando, no un cambio
  de modelo.
