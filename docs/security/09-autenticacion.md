# I. Autenticación (django-allauth)

---

## I.1 Decisión de fondo: no hay registro público

Un sistema de RRHH **no tiene usuarios anónimos que se registran solos**. Permitir
`signup` abierto significaría que cualquiera con la URL crea una cuenta
autenticada, y a partir de ahí toda la seguridad depende de que ninguna vista
confunda *autenticado* con *autorizado* — exactamente el error que la regla 31
advierte.

**Decisión adoptada ([ADR-004](../decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md)):
dos vías de alta, ambas iniciadas por RRHH.** Se evaluaron seis alternativas; se
rechazaron el auto-registro con validación de PII (oráculo de números de
identificación) y el auto-registro por dominio de correo (traslada el control de
acceso al control del buzón). El SSO corporativo queda diferido a ADR-017.

### I.1.1 Vía A — invitación por correo (Fase 2)

```
RRHH crea el Employee
        ↓
RRHH invita → se crea el User con contraseña inutilizable
        ↓
Correo con token firmado, de un solo uso y con expiración
        ↓
La persona fija contraseña y verifica su correo en un paso
        ↓
Cuenta activa, con su grupo asignado
```

Reutiliza el mecanismo de restablecimiento de contraseña de Django (token
firmado, un solo uso, expiración). No se implementa criptografía propia
(regla 30).

**Es el único mecanismo de la Fase 2**, cuyo alcance son cuentas de RRHH y
jefaturas — un colectivo que dispone de correo corporativo.

### I.1.2 Vía C — código de activación (Fase 6)

Para el personal sin correo corporativo, cuando entre la plantilla general con el
portal de autoservicio. **Se especifica ahora y se construye entonces** (regla 56).

```
RRHH genera el código → se muestra UNA sola vez y se entrega en mano
        ↓                 (en la base solo queda su hash)
La persona abre /accounts/activate/ e introduce el código
        ↓
Declara un correo (personal si no tiene corporativo) y su contraseña
        ↓
El código pasa a REDEEMED; se envía la verificación del correo
        ↓
Cuenta activa
```

Lo que se entrega **no es una contraseña**: es un token que solo sirve para
activar. Si el papel se extravía, lo comprometido es un secreto revocable y
caduco, no una credencial permanente.

| Propiedad | Valor | Motivo |
|---|---|---|
| Entropía | **80 bits** — 16 caracteres Crockford Base32, agrupados `XXXX-XXXX-XXXX-XXXX` | Legible y transcribible desde papel; inviable de forzar incluso con la base filtrada |
| Almacenamiento | `HMAC-SHA256(code, SECRET_KEY)` | El valor en claro nunca se persiste. El HMAC impide precomputación si se filtra la base sin la clave. Un hash lento no aporta aquí: no hay diccionario contra 80 bits aleatorios |
| Vigencia | 72 h configurable | — |
| Usos | Uno | — |
| Pendientes por usuario | Máximo uno (constraint parcial) | Emitir uno nuevo revoca el anterior |
| Respuesta ante código inválido, usado o caducado | **Idéntica** | No revela si el código existió |
| Límite de tasa | 5 intentos / hora / IP y tope global | Fuerza bruta |
| Auditoría | `ACTIVATION_CODE_ISSUE`, `ACTIVATION_CODE_REDEEM`, `ACTIVATION_CODE_FAILED`, `ACTIVATION_CODE_REVOKE` | — |

**Identidad de acceso.** El código arranca la identidad, no la sustituye:
`email` sigue siendo `USERNAME_FIELD` y se declara durante el canje. Consecuencia
aceptada: un correo personal como identidad queda fuera del control de la
organización, por lo que la cuenta debe desactivarse explícitamente al terminar
el contrato — el sistema ya lo hace.

**Caso residual declarado:** quien no tiene ningún correo ni posibilidad de
obtenerlo **no tiene cuenta**; RRHH opera en su nombre. Si ese colectivo resulta
significativo, hay que reabrir la decisión sobre `USERNAME_FIELD` **antes** de la
Fase 6: cambiarlo después de las migraciones es tan caro como sustituir el modelo
de usuario.

### I.1.3 Cómo se cierra el registro

Dos mecanismos a la vez, deliberadamente redundantes:

- `ACCOUNT_ADAPTER` propio con `is_open_for_signup(request) → False`.
- Las rutas de `signup` no se incluyen en el enrutamiento.

Ninguno basta solo: retirar la URL no protege si una actualización de allauth la
reintroduce, y el adaptador solo deja enlazada una ruta que responde error.

---

## I.2 Configuración de allauth

| Ajuste | Valor | Motivo |
|---|---|---|
| `ACCOUNT_LOGIN_METHODS` | `{"email"}` | El correo es la identidad; `username` no aporta nada |
| `ACCOUNT_USER_MODEL_USERNAME_FIELD` | `None` | **Imprescindible.** Sin declararlo, allauth busca `user.username` y falla, porque nuestro modelo no lo tiene |
| `ACCOUNT_SIGNUP_FIELDS` | `["email*", "password1*", "password2*"]` | Sin campos de nombre: la identidad civil vive en `Person` |
| `ACCOUNT_EMAIL_VERIFICATION` | `"mandatory"` | Sin correo verificado no hay acceso |
| `ACCOUNT_UNIQUE_EMAIL` | `True` | — |
| `ACCOUNT_ADAPTER` | `accounts.adapters.NoPublicSignupAdapter` | Cierra el registro |
| `ACCOUNT_RATE_LIMITS` | `login_failed` `5/5m/key,20/5m/ip`; `reset_password` `5/h/ip,3/h/key`; `confirm_email` `3/h/key`; `change_password` `5/m/user` | Fuerza bruta y abuso de correo. Sustituye a los obsoletos `ACCOUNT_LOGIN_ATTEMPTS_*` |
| `ACCOUNT_SESSION_REMEMBER` | `False` | Sesión de RRHH: no se recuerda por defecto |
| `ACCOUNT_LOGOUT_ON_GET` | `False` | Un `GET` no debe cerrar sesión (evita CSRF de logout) |
| `ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE` | `True` | Invalida sesiones tras cambiar contraseña |
| `ACCOUNT_EMAIL_SUBJECT_PREFIX` | `"[RRHH] "` | — |
| `ACCOUNT_PREVENT_ENUMERATION` | `True` | El mensaje de "correo no encontrado" no revela si existe la cuenta |
| `LOGIN_REDIRECT_URL` | `"/"` | La portada es el panel autenticado |
| `ACCOUNT_DEFAULT_HTTP_PROTOCOL` | `"http"` en desarrollo, **`"https"` en producción** | Un enlace `http` en un correo es una credencial viajando en claro |

**Proveedores sociales: ninguno.** No se instala `allauth.socialaccount`. Añadir
Google Workspace más adelante es una decisión de negocio que se documentará como
ADR; hoy sería superficie de ataque sin uso.

---

## I.3 Contraseñas

- **Hashing:** Django gestiona todo. **Nunca** se escribe criptografía propia
  (regla 30). Se propone **Argon2** como hasher principal
  (`argon2-cffi`), con PBKDF2 como respaldo en la lista para migrar hashes
  antiguos de forma transparente.
  *Justificación de la dependencia extra:* Argon2id es la recomendación actual
  de OWASP para almacenamiento de contraseñas y `argon2-cffi` es la vía que la
  propia documentación de Django señala. Se documenta como **ADR-013**; si se
  rechaza, el PBKDF2 por defecto de Django sigue siendo aceptable.
- **Validadores** activos: longitud mínima **12** (por encima del 8 por defecto),
  similitud con atributos del usuario, contraseñas comunes, no solo numérica.
- **Cambio obligatorio:** `User.must_change_password` fuerza el cambio en el
  primer acceso tras un alta o un restablecimiento hecho por RRHH. Un middleware
  redirige a la vista de cambio, con una lista corta de rutas exentas (logout,
  la propia vista de cambio, estáticos).
- **Nunca** se registra, muestra ni transmite una contraseña en claro, ni
  siquiera en `DEBUG`. Django ya oculta estos campos en el reporte de error; el
  filtro de logs lo refuerza (ver [K](11-seguridad.md)).

---

## I.4 Sesiones

| Ajuste | Desarrollo | Producción | Motivo |
|---|---|---|---|
| `SESSION_ENGINE` | BD | BD | Permite invalidación del lado servidor. Con cookies firmadas no se puede cerrar una sesión robada |
| `SESSION_COOKIE_SECURE` | `False` | **`True`** | — |
| `SESSION_COOKIE_HTTPONLY` | `True` | `True` | Un XSS no puede leer la cookie |
| `SESSION_COOKIE_SAMESITE` | `"Lax"` | `"Lax"` | Bloquea CSRF entre sitios manteniendo la navegación normal |
| `SESSION_COOKIE_AGE` | 8 h | **8 h** | Una jornada laboral |
| `SESSION_EXPIRE_AT_BROWSER_CLOSE` | `False` | `True` | Estaciones compartidas |
| `SESSION_COOKIE_NAME` | `rrhh_sessionid` | ídem | No anunciar el framework |

**Fijación de sesión:** Django regenera la clave de sesión en el login
(`cycle_key`). No se implementa nada a mano; se **verifica con un test** que la
clave cambia tras autenticarse.

**Cierre de sesión ante cambios de privilegio:** al modificar los grupos de un
usuario, al desactivarlo o al terminar su contrato, el servicio invalida sus
sesiones activas. Sin esto, un usuario despedido conserva acceso hasta que expire
su cookie — un hallazgo clásico de auditoría.

---

## I.5 Funcionalidades de cuenta

| Función | Origen | Nota |
|---|---|---|
| Login / Logout | allauth | Logout solo por `POST` |
| Verificación de correo | allauth | Obligatoria |
| Restablecimiento de contraseña | allauth | Con protección de enumeración y limitación de tasa |
| Cambio de contraseña | allauth | Cierra las demás sesiones |
| Alta por invitación | **Propia** (`accounts.services.invite_user`) | Solo HR_ADMIN. Auditada. **Fase 2** |
| Alta por código de activación | **Propia** (`accounts.services.issue_activation_code` / `redeem_activation_code`) | Solo HR_ADMIN emite. El canje es público con límite de tasa. **Fase 6** |
| Cambio de correo | allauth | Requiere verificar el nuevo correo antes de activarlo |
| Perfil | **Propia** | Muestra datos de `Person`/`Employee`; el empleado edita únicamente contacto y contactos de emergencia |
| MFA | allauth (`allauth.mfa`) | **Fase 9.** Recomendada como obligatoria para HR_ADMIN y SUPERADMIN. No se activa ahora para no bloquear el arranque, pero se elige allauth como base precisamente para tenerla disponible sin cambiar de librería |

---

## I.6 Eventos de autenticación auditados

Mediante señales (`user_logged_in`, `user_logged_out`, `user_login_failed`) y las
señales propias de allauth:

| Evento | `action` | `outcome` | Datos |
|---|---|---|---|
| Login correcto | `LOGIN` | `SUCCESS` | actor, IP, user-agent |
| Login fallido | `LOGIN_FAILED` | `FAILURE` | correo **intentado**, IP. **Nunca la contraseña** |
| Logout | `LOGOUT` | `SUCCESS` | — |
| Cambio de contraseña | `PASSWORD_CHANGE` | `SUCCESS` | Sin el valor |
| Solicitud de restablecimiento | `PASSWORD_RESET_REQUEST` | `SUCCESS` | Correo, IP |
| Restablecimiento completado | `PASSWORD_RESET_COMPLETE` | `SUCCESS` | — |
| Correo verificado | `EMAIL_VERIFIED` | `SUCCESS` | — |
| Invitación creada | `USER_CREATE` | `SUCCESS` | Actor = quien invita |
| Código de activación emitido | `ACTIVATION_CODE_ISSUE` | `SUCCESS` | Actor, usuario destino, expiración. **Nunca el código** |
| Código canjeado | `ACTIVATION_CODE_REDEEM` | `SUCCESS` | Usuario, IP |
| Canje fallido | `ACTIVATION_CODE_FAILED` | `FAILURE` | IP. **Sin el código intentado**: registrarlo convertiría la bitácora en un diccionario de tokens |
| Código revocado | `ACTIVATION_CODE_REVOKE` | `SUCCESS` | Actor, motivo |
| Desactivación | `USER_DEACTIVATE` | `SUCCESS` | Motivo |

Registrar el correo intentado en un login fallido es deliberado: es la señal que
permite detectar fuerza bruta y ataques de *credential stuffing* (índice I-22).
No constituye exposición de datos sensibles, ya que el correo corporativo no es
un secreto.

---

## I.7 Tests de autenticación (Fase 2)

- Login con credenciales válidas, inválidas y de usuario inactivo.
- Bloqueo tras N intentos fallidos.
- Sin acceso sin verificar el correo.
- La clave de sesión cambia tras el login (fijación de sesión).
- Logout por `GET` **no** cierra sesión; por `POST`, sí.
- `/accounts/signup/` responde 404 o 403 (registro cerrado).
- El restablecimiento no revela si el correo existe.
- El token de restablecimiento es de un solo uso y expira.
- Cambiar la contraseña invalida las demás sesiones.
- `must_change_password` redirige y no se puede saltar navegando a otra URL.
- Toda vista autenticada redirige al login cuando el usuario es anónimo
  (parametrizado sobre **toda** la tabla de URLs, no una muestra).
- Un `POST` directo al endpoint de signup de allauth **no** crea usuario.
- `is_open_for_signup()` devuelve `False`.
- Toda creación de `User` emite `USER_CREATE` con actor no nulo.

### Tests del código de activación (Fase 6)

- El valor en claro del código **no** aparece en la base (se busca la cadena
  emitida en todas las columnas de texto de la tabla).
- Código válido → activa; el mismo código una segunda vez → falla.
- Código caducado, revocado e inexistente producen **la misma respuesta** (cuerpo
  y código de estado) que un código con formato válido pero falso.
- Emitir un código nuevo revoca el pendiente.
- El límite de tasa por IP bloquea al sexto intento.
- Un canje fallido registra `ACTIVATION_CODE_FAILED` **sin** el código intentado.
- El canje exige verificar el correo declarado antes de dar acceso pleno.
