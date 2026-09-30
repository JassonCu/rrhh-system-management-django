# Revisión de seguridad — Fase 7 (Documentos)

- **Fecha:** 2026-09-19
- **Alcance:** `apps/documents` completo; permisos nuevos en `accounts.roles`; pestaña «Expediente» en `employees`; tres acciones de auditoría nuevas
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase), con la cadena de [§K.4](11-seguridad.md#k4-seguridad-de-archivos) como criterio de cierre
- **Resultado:** **aprobada**, con la cadena completa implementada y probada, dos desviaciones aceptadas y una decisión pendiente del negocio

---

## Método

- Se recorrió la cadena de §K.4 **paso por paso**, escribiendo una prueba por
  cada forma conocida de saltársela: ejecutable renombrado, nombre con
  `../../`, archivo sobredimensionado, extensión fuera de la allowlist,
  `content_type` mentiroso y archivo vacío.
- Se preguntó por cada camino al archivo: la vista de descarga, una URL directa
  a `/media/`, y la ruta en disco. Los tres tienen prueba.
- Se siguió el dato sensible: quién ve que un documento **existe** y quién puede
  **abrirlo**, que en esta fase no son lo mismo.
- Se revisó qué entra en la bitácora: identificación del documento, nunca su
  contenido.

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Autenticación explícita en toda vista | ✅ | `tests/security/test_url_coverage.py` cubre las 7 URLs nuevas |
| 2 | Comprobación de permiso en toda vista | ✅ | Matriz rol × vista en `documents/tests/test_authorization.py` |
| 3 | Todo acceso a objeto pasa por un selector | ✅ | `get_document_or_404` y `get_employee_or_404`; la ficha sale de la URL, nunca del POST |
| 4 | Sin `fields = "__all__"` | ✅ | `test_form_safety.py` |
| 5 | Sin campos de privilegio ni FK de propiedad en formularios | ✅ | El formulario de subida no expone `employee`, `checksum_sha256` ni `stored_path` |
| 6 | Sin `\|safe` sobre datos de usuario | ✅ | El nombre subido se muestra escapado por plantilla |
| 7 | Sin JS ni CSS en línea | ✅ | `test_template_safety.py` |
| 8 | Cambios de estado por `POST` con CSRF | ✅ | Subir y archivar; el GET de archivado solo confirma (probado) |
| 9 | Datos sensibles fuera de logs y URLs | ✅ | La bitácora guarda código, tipo y checksum; jamás el contenido |
| 10 | Acciones relevantes auditadas | ✅ | Subida, **descarga**, archivado y catálogo de tipos |
| 11 | Tests de acceso no autorizado por vista | ✅ | Incluye `AUDITOR` y `HR_MANAGER` intentando archivar |
| 12 | Test de IDOR por recurso con identificador | ✅ | Documento ajeno → 404; confidencial sin permiso → 403 |
| 13-16 | Bandit, `pip-audit`, `detect-secrets`, `check --deploy` | ✅ | Sin hallazgos; sin dependencias nuevas |
| 17 | Errores sin información interna | ✅ | Cada paso de la cadena tiene su mensaje en lenguaje llano |

### Criterio de cierre del roadmap

| Caso exigido | Prueba |
|---|---|
| Ejecutable renombrado a `.pdf` | `test_an_executable_renamed_to_pdf_is_refused` |
| Path traversal en el nombre | `test_a_traversal_file_name_leaves_no_path` |
| Archivo sobredimensionado | `test_an_oversized_file_is_refused`, `test_the_global_cap_wins_over_the_type` |
| Descarga por usuario no autorizado | `test_someone_elses_document_is_not_found`, `test_a_confidential_document_is_visible_but_not_openable` |
| Descarga directa por URL de `MEDIA_ROOT` | `test_media_is_not_served_directly` |

**Métricas:** 1643 pruebas, 93,23 % de cobertura. La app de documentos aporta 57.

---

## Cómo queda la cadena

| Paso | Qué hace | Si falla |
|---|---|---|
| 1. Tamaño | Contra el tope del tipo y el global de 25 MB, antes de leer nada | «Ese archivo supera el tamaño permitido…» |
| 2. Extensión | Allowlist del tipo, cruzada con la global (`pdf,png,jpg,jpeg,docx`) | «Ese formato no se acepta…» |
| 3. Firma real | Se leen los primeros bytes: un `.pdf` que empieza con `MZ` se cae | «El archivo dice ser de ese formato, pero su contenido no lo es» |
| 4. `content_type` | Se comprueba; **no decide** | «El tipo de archivo que informa su navegador no coincide» |
| 5. Nombre | Se **descarta**: la ruta es `documents/<public_id>/<uuid4>.<ext>` | — |
| 6. Checksum | SHA-256 por bloques; alimenta el índice que evita duplicados | «Ese mismo archivo ya está en este expediente» |
| 7. Antivirus | **No en esta fase**: ver D-1 | — |

---

## Hallazgos

Ninguno de gravedad: la cadena se implementó contra §K.4 desde el primer
commit y las pruebas se escribieron junto con ella. Se corrigieron dos cosas
durante la construcción:

### C-1 — El duplicado llegaba como error de validación a media transacción

`full_clean()` validaba la restricción única y levantaba `ValidationError`
dentro del bloque atómico, en vez del `ConflictError` que la vista sabe
traducir. Ahora el servicio comprueba el checksum antes de escribir y deja el
`IntegrityError` como red para la carrera entre dos subidas simultáneas.

### C-2 — Archivar bloqueaba volver a subir el archivo corregido

El índice único por checksum miraba todos los documentos. Ahora es **parcial**
(`is_active = TRUE`): archivar un documento mal subido libera el checksum para
volver a subirlo. **Prueba:** `test_archiving_frees_the_checksum_for_a_new_upload`.

---

## Desviaciones aceptadas

### D-1 — Sin antivirus

§K.4 ya lo preveía: el sistema no escanea el contenido. Mitigaciones actuales:
la firma real debe coincidir con la extensión, la allowlist es corta, el archivo
**nunca** se sirve `inline` y `X-Content-Type-Options: nosniff` impide que el
navegador adivine el tipo. Si el negocio lo exige, se integra ClamAV como
servicio aparte (Fase 9). **Un PDF malicioso sigue siendo posible**: esta
desviación es real, no cosmética.

### D-2 — La entrega la hace Django, no el servidor web

Cada descarga pasa por el proceso de la aplicación. Es lo correcto hoy —la
autorización y la bitácora viven ahí— y el volumen previsto lo soporta. En
producción se delegará con `X-Accel-Redirect` o `X-Sendfile`, **manteniendo la
autorización en Django**: es un cambio de una línea porque la vista ya es el
único camino al archivo.

---

## Decisión pendiente del negocio

| # | Pregunta | Por qué importa |
|---|---|---|
| P-1 | **¿Cuánto se conserva cada tipo de documento y qué pasa al vencer el plazo?** Hoy `retention_years` se captura pero **nadie lo aplica**: ningún documento se purga | Conservar de más es un riesgo de privacidad; purgar sin política escrita es destruir prueba. Al decidirlo hará falta un comando de retención y, con él, su propia revisión |

---

## Addendum — 2026-09-27

Una revisión posterior del módulo de reportes encontró dos defectos en esta
fase, ya corregidos. Se dejan aquí porque pertenecen al expediente, no a los
reportes; el detalle está en
[la revisión del módulo de reportes](revision-reportes.md).

- **Archivar no cortaba la descarga.** El selector de la vista de descarga
  alcanzaba también a los documentos archivados, así que un enlace guardado
  seguía entregando el archivo. La pantalla de archivado promete lo contrario.
  Corregido: los archivados quedan fuera del alcance por omisión.
- **Un tipo confidencial podía ofrecerse a la propia persona** si el catálogo lo
  marcaba a la vez como «lo sube el empleado». Corregido: la rama de
  autoservicio excluye los confidenciales.

**Lo que esto dice del checklist:** el punto 12 (IDOR por recurso) se verificó
sobre documentos **activos**. Un documento archivado es el mismo recurso con el
acceso supuestamente retirado, y esa transición no se había probado.

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Sin antivirus (D-1) | Aceptado; revisar en Fase 9 |
| `retention_years` no se aplica (P-1) | Pendiente de decisión del negocio |
| `MEDIA_ROOT` debe quedar fuera del árbol servido **también en producción** | Es configuración de despliegue: el código no puede garantizarlo solo |
| Copias de respaldo de `MEDIA_ROOT` | No hay política definida; un expediente perdido no se recupera del volcado de base |
| Tareas programadas, `MINIMUM_MONTHLY_SALARY`, algoritmo del NIT | Heredados; siguen siendo bloqueantes |
