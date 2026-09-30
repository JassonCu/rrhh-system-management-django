# K. Seguridad

Cubre las reglas 29, 33, 34, 35, 37, 49 y 50. La autenticación está en
[I](09-autenticacion.md) y la autorización en [J](10-autorizacion.md).

---

## K.1 Ajustes de seguridad de Django por entorno

No se copian ajustes de producción al entorno local (regla 29): `SECURE_SSL_REDIRECT`
en desarrollo produce redirecciones infinitas y lleva a desactivarlo todo por
frustración.

| Ajuste | Desarrollo | Testing | Producción | Nota |
|---|---|---|---|---|
| `DEBUG` | `True` | `False` | **`False`** | Con `True` en producción se filtra el entorno completo |
| `SECRET_KEY` | Local, de descarte | Fija de test | **De entorno, sin defecto** | Si falta, el arranque falla |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | `testserver` | **Lista explícita** | Previene *Host header injection* |
| `CSRF_TRUSTED_ORIGINS` | — | — | **Explícito** | Necesario tras un proxy |
| `CSRF_COOKIE_SECURE` | `False` | `False` | **`True`** | — |
| `CSRF_COOKIE_HTTPONLY` | `False` | `False` | `False` | **Deliberado:** debe ser `False` para que el JS pueda leer el token en peticiones `fetch`. La protección real es `SameSite` + la validación del servidor |
| `CSRF_COOKIE_SAMESITE` | `Lax` | `Lax` | `Lax` | — |
| `SESSION_COOKIE_SECURE` | `False` | `False` | **`True`** | — |
| `SESSION_COOKIE_HTTPONLY` | `True` | `True` | `True` | — |
| `SESSION_COOKIE_SAMESITE` | `Lax` | `Lax` | `Lax` | — |
| `SECURE_SSL_REDIRECT` | `False` | `False` | **`True`** | — |
| `SECURE_HSTS_SECONDS` | `0` | `0` | **`31536000`** | Un año. Se activa **solo** con HTTPS ya funcionando |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `False` | `False` | `True` | — |
| `SECURE_HSTS_PRELOAD` | `False` | `False` | `True` | Tras verificar el dominio |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` | `True` | `True` | Barato y siempre correcto |
| `SECURE_REFERRER_POLICY` | `same-origin` | ídem | `same-origin` | Evita filtrar URLs con identificadores a terceros |
| `X_FRAME_OPTIONS` | `DENY` | `DENY` | `DENY` | Clickjacking. La app no se embebe en ningún sitio |
| `SECURE_CROSS_ORIGIN_OPENER_POLICY` | `same-origin` | ídem | `same-origin` | Aislamiento de ventana |
| `SECURE_PROXY_SSL_HEADER` | — | — | Solo si hay proxy **de confianza** | Configurarlo sin proxy permite falsificar `is_secure()` |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | 2.5 MB | ídem | 2.5 MB | — |
| `FILE_UPLOAD_MAX_MEMORY_SIZE` | 2.5 MB | ídem | 2.5 MB | Más allá, va a disco |
| `DATA_UPLOAD_MAX_NUMBER_FIELDS` | 1000 | ídem | 1000 | Anti-DoS de formularios |

`python manage.py check --deploy` se ejecuta en CI con la configuración de
producción y **debe salir sin advertencias** (regla 48).

---

## K.2 Content Security Policy

Objetivo: una política estricta **sin `unsafe-inline` ni `unsafe-eval`**
(regla 34). Esto condiciona el frontend desde el primer commit — introducirla al
final obligaría a reescribir plantillas.

| Directiva | Valor | Justificación |
|---|---|---|
| `default-src` | `'self'` | Base restrictiva: lo no declarado, prohibido |
| `script-src` | `'self' 'nonce-{random}'` | Sin `unsafe-inline`. Los scripts van en archivos; los pocos inline llevan nonce por petición |
| `style-src` | `'self' 'nonce-{random}'` | Sin `unsafe-inline`. Prohíbe atributos `style=` en línea |
| `img-src` | `'self' data:` | `data:` para iconos SVG embebidos. Sin dominios externos |
| `font-src` | `'self'` | Fuentes autoalojadas. Sin Google Fonts (privacidad + un origen menos) |
| `connect-src` | `'self'` | `fetch` solo al propio origen |
| `form-action` | `'self'` | **Impide que un XSS reenvíe un formulario a un servidor externo** |
| `frame-ancestors` | `'none'` | Clickjacking; complementa `X-Frame-Options` |
| `base-uri` | `'none'` | Impide secuestrar rutas relativas con `<base>` |
| `object-src` | `'none'` | Sin Flash/applets |
| `frame-src` | `'none'` | No se embebe nada |
| `upgrade-insecure-requests` | activo en producción | — |
| `report-uri` / `report-to` | Endpoint interno | Fase 9; registra violaciones sin bloquear al usuario |

**Implementación:** `django-csp`. Se prefiere a un middleware propio porque la
generación de nonce por petición, su inyección en la plantilla y la variación por
vista son fáciles de implementar mal; la librería es pequeña, está mantenida y
resuelve exactamente ese problema. **ADR-007.**

**Consecuencias para el frontend, aceptadas conscientemente:**

- Nada de `onclick="..."` ni `<script>` con código embebido: se usan
  `addEventListener` desde archivos en `static/js/`.
- Nada de `style="..."` en línea: clases CSS.
- Los datos que el JS necesita se pasan por atributos `data-*` y se leen con
  `dataset`, o mediante `json_script` de Django (que es seguro por diseño).
- **Despliegue por fases (completado):** estuvo en
  `Content-Security-Policy-Report-Only` durante las Fases 1–2 para detectar
  violaciones sin romper nada. **Desde el cierre de la Fase 2 bloquea en todos
  los entornos**, incluido desarrollo: dejarla en modo informe habría sido no
  tener CSP.

---

## K.3 Protecciones nativas de Django y cómo se preservan

| Amenaza | Protección | Cómo se conserva |
|---|---|---|
| **XSS** | Autoescape de plantillas | Prohibido `\|safe`/`mark_safe` sobre datos de usuario. CSP como segunda barrera. Test que busca `\|safe` en las plantillas |
| **CSRF** | `CsrfViewMiddleware` + `{% csrf_token %}` | `@csrf_exempt` prohibido sin ADR. Cambios de estado solo por `POST`. Test de `POST` sin token |
| **SQL Injection** | ORM parametrizado | Sin `raw()`/`extra()`/`RawSQL` sin aprobación en revisión. Bandit lo detecta |
| **Fijación de sesión** | `cycle_key()` en el login | Test explícito |
| **Clickjacking** | `X_FRAME_OPTIONS=DENY` + `frame-ancestors 'none'` | — |
| **Host header injection** | `ALLOWED_HOSTS` | Lista explícita; nunca `["*"]` |
| **Open redirect** | `url_has_allowed_host_and_scheme` | Todo `?next=` se valida. Test con URL absoluta externa |
| **Mass assignment** | Campos explícitos en formularios | Prohibido `fields = "__all__"`. Test que recorre todos los formularios |
| **IDOR** | Selectores con alcance | Ver [J.4](10-autorizacion.md#j4-autorización-a-nivel-de-objeto). Suite dedicada |
| **Broken access control** | Tres capas en cada vista | Matriz parametrizada de tests |
| **Escalada de privilegios** | [J.5](10-autorizacion.md#j5-prevención-de-escalada-de-privilegios) | Tests dedicados |
| **Path traversal** | Nombres generados, nunca los del usuario | Ver K.4. Test con `../../etc/passwd` como nombre de archivo |
| **Subida insegura** | Validación en cadena | Ver K.4 |
| **Exposición de datos sensibles** | Clasificación [G.19](../database/06-diccionario-de-datos.md#g19-clasificación-de-datos) | Enmascarado, filtro de logs, sin PII en URLs |
| **Errores mal manejados** | `DEBUG=False` + páginas propias | Ver K.6 |
| **Fuerza bruta** | Límites de tasa de allauth | Test de bloqueo |
| **Enumeración de usuarios** | `ACCOUNT_PREVENT_ENUMERATION` | Test comparando respuestas |
| **Dependencias vulnerables** | `pip-audit` en CI | Ver [L](../development/12-devsecops.md) |

---

## K.4 Seguridad de archivos

Los documentos de RRHH (contratos, constancias, expedientes médicos) son de los
datos más sensibles del sistema (regla 33).

### Almacenamiento

- `MEDIA_ROOT` está **fuera** del árbol servido por el servidor web. Nunca se
  publica `/media/` como directorio estático.
- Ruta generada: `documents/<employee_public_id>/<uuid4>.<ext_validada>`. El
  nombre subido por el usuario **jamás** toca el sistema de archivos; se guarda en
  la columna `original_filename` solo para mostrarlo (escapado).
- `FILE_UPLOAD_PERMISSIONS = 0o600`.

### Validación de subida (cadena completa, en este orden)

1. **Tamaño** — antes de leer nada: `size <= DocumentType.max_size_mb`, con tope
   global de 25 MB.
2. **Extensión** — allowlist por tipo de documento (`pdf`, `png`, `jpg`, `jpeg`,
   `docx`). Nunca una denylist.
3. **Contenido real (magic bytes)** — se leen los primeros bytes y se comprueba
   que la firma coincide con la extensión declarada. Un `.pdf` que empieza con
   `<?php` o `MZ` se rechaza. Se implementa con una tabla de firmas propia para
   el puñado de tipos permitidos: `python-magic` requiere `libmagic`, que en
   Windows es una fricción de instalación innecesaria para cinco formatos.
4. **`content_type` declarado** — se comprueba pero **no se confía en él**: lo
   envía el cliente.
5. **Nombre** — se descarta; se genera uno nuevo.
6. **Checksum SHA-256** — se calcula y almacena: detecta duplicados y permite
   verificar la integridad más tarde.
7. **Antivirus** — no en esta fase. Si el negocio lo exige, se integra ClamAV en
   un servicio aparte (Fase 9). Se documenta como riesgo aceptado.

### Descarga

**Nunca** se sirve un archivo por URL directa. El flujo es:

```
GET /documents/<public_id>/download/
        ↓ @login_required
        ↓ selector documents_visible_for(user) → 404 si no está en el alcance
        ↓ comprobación de tipo sensible (view_sensitive_document)
        ↓ AuditEvent DOCUMENT_DOWNLOAD  ← antes de entregar el archivo
        ↓ FileResponse con Content-Disposition: attachment; filename="<saneado>"
        ↓ X-Content-Type-Options: nosniff
```

- `Content-Disposition: attachment` **siempre**: nunca `inline`, para que un HTML
  o SVG malicioso no se ejecute en el origen de la aplicación.
- El `filename` se sanea (sin comillas, sin saltos de línea) para evitar
  inyección de cabeceras.
- La ruta se resuelve y se verifica que queda **dentro** de `MEDIA_ROOT` antes de
  abrir el archivo (defensa contra *path traversal*, aunque la ruta sea generada).
- En producción, la entrega se delegará al servidor web con `X-Accel-Redirect`
  (nginx) o `X-Sendfile` — **manteniendo la autorización en Django**. Es un
  cambio de una línea porque la vista ya es el único punto de acceso.

---

## K.5 Logging

| Nivel | Uso |
|---|---|
| `DEBUG` | Solo en desarrollo. Nunca activo en producción |
| `INFO` | Eventos de negocio relevantes (contrato creado, ausencia aprobada) |
| `WARNING` | Intentos denegados, validaciones fallidas repetidas, límites alcanzados |
| `ERROR` | Excepciones controladas que impiden completar una operación |
| `CRITICAL` | Fallo de infraestructura, imposibilidad de escribir en la bitácora |

**Nunca se registra** (regla 49): contraseñas (ni sus hashes), tokens, cookies,
datos de sesión, `SECRET_KEY`, cabeceras `Authorization`, contenido de documentos,
números de identificación completos.

Mecanismos:

- **Filtro de redacción** aplicado a todos los handlers, que enmascara claves
  sospechosas (`password`, `token`, `secret`, `csrf`, `session`, `authorization`,
  `api_key`, `dpi`, `nit`). Tiene test propio.
- **`request_id`** (UUID por petición, generado en un middleware) presente en cada
  línea de log y en `AuditEvent.request_id`, lo que permite correlacionar el
  rastro técnico con el rastro de negocio.
- Formato: legible en desarrollo, **JSON en producción** — así el paso futuro a un
  agregador de logs no exige reescribir nada.
- **Auditoría ≠ logging.** El log es operativo y efímero; `AuditEvent` es
  evidencia persistente y consultable. Un evento de seguridad va a los dos.

---

## K.6 Manejo de errores

- `DEBUG = False` en producción, verificado por `check --deploy` en CI.
- Plantillas propias `400.html`, `403.html`, `404.html`, `500.html`: mensaje claro,
  sin detalles internos, sin números de versión, con enlace de vuelta.
- `500.html` no ejecuta consultas ni usa el context processor (podría fallar
  también); es prácticamente HTML estático.
- Los tracebacks van al log del servidor con su `request_id`; el usuario recibe
  ese identificador para reportarlo. No se muestra ninguna información interna.
- Los mensajes de error de dominio no filtran existencia: "no se encontró el
  recurso" en lugar de "no tienes permiso para ver al empleado Juan Pérez".
- `ADMINS` configurado para recibir los 500 por correo mientras no haya un sistema
  de observabilidad.

---

## K.7 Cobertura de auditoría

**Regla:** todo servicio que escriba en la base deja un evento en la bitácora.
No es una intención, es una prueba: `tests/security/test_audit_coverage.py`
recorre el árbol sintáctico de cada `services.py` y **falla** si aparece un
servicio que guarda algo sin auditar.

La prueba comprueba cuatro cosas:

| # | Qué fija |
|---|---|
| 1 | Ningún servicio público escribe sin auditar, salvo excepción declarada |
| 2 | Cada excepción trae su motivo escrito |
| 3 | No quedan excepciones obsoletas: si un servicio ya audita, la excepción se borra |
| 4 | Ninguna acción declarada en `AuditAction` queda sin emitirse (salvo las de fases futuras) |

### Excepciones vigentes

| Servicio | Por qué no audita |
|---|---|
| `audit.services.record` | Es quien escribe la bitácora; auditarla sería un bucle |
| `accounts.services.invalidate_sessions_for` | Cierra sesiones como consecuencia de un cambio de rol o una baja, que sí se auditan |
| `reports.services.export_to_excel` | El `save` es el del libro en memoria, no una escritura en la base; la exportación se audita aparte |

### El caso del marcaje

El marcaje **propio** no genera evento: son miles al mes y ahogarían la señal
(ADR-021). El registro ya guarda quién marcó y desde qué origen, y es su propia
prueba. Lo que sí se audita —porque es excepcional— es **marcar por cuenta de
otra persona** (`ATTENDANCE_PUNCH_FOR_OTHER`).

### Lo que se cerró al aplicar la regla

Al escribir la prueba aparecieron cuatro huecos que llevaban tiempo abiertos:

- **El devengo mensual de ausencias** movía el saldo de cada persona sin dejar
  rastro (`LEAVE_ACCRUAL`).
- **El borrador de una solicitud** no se registraba (`LEAVE_CREATE`).
- **Pedir restablecer una contraseña** no se registraba, solo completarla
  (`PASSWORD_RESET_REQUEST`). Es la señal temprana de un intento de robo de
  cuenta.
- **Cambiar los permisos de un rol** en un despliegue no dejaba constancia
  (`PERMISSION_CHANGE`).

---

## K.8 Gestión de secretos

- Nada de secretos en el repositorio (regla 47). `.env` en `.gitignore` desde el
  primer commit.
- `.env.example` con todas las claves y valores obviamente ficticios.
- `detect-secrets` en pre-commit y en CI, con una línea base versionada.
- Si un secreto llega a Git: **se rota primero**, se limpia el historial después.
  Reescribir el historial no lo invalida — quien ya lo clonó lo tiene.
- El `SECRET_KEY` de producción se genera con `secrets.token_urlsafe(64)` y se
  guarda en el gestor de secretos de la plataforma, nunca en un archivo del
  servidor legible por todos.

---

## K.9 Revisión de seguridad por fase

Checklist obligatorio antes de cerrar cada fase (regla 59):

```
[ ] Toda vista nueva tiene autenticación explícita
[ ] Toda vista nueva tiene comprobación de permiso
[ ] Todo acceso a objeto pasa por un selector con alcance
[ ] Ningún formulario usa fields = "__all__"
[ ] Ningún formulario expone is_staff, is_superuser, groups ni FKs de propiedad
[ ] Las plantillas nuevas no usan |safe sobre datos de usuario
[ ] Las plantillas nuevas no llevan JS ni CSS en línea (CSP)
[ ] Los cambios de estado son POST con CSRF
[ ] Los datos sensibles no aparecen en logs ni en URLs
[ ] Las acciones relevantes emiten AuditEvent
[ ] Existen tests de acceso no autorizado (403/404) para cada vista nueva
[ ] Existe un test de IDOR por cada recurso con identificador en la URL
[ ] bandit sin hallazgos de severidad media o alta
[ ] pip-audit sin vulnerabilidades conocidas explotables
[ ] detect-secrets sin hallazgos nuevos
[ ] manage.py check --deploy sin advertencias
[ ] Los errores no filtran información interna
```
