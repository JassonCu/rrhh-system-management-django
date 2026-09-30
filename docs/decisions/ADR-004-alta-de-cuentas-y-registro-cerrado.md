# ADR-004 — Alta de cuentas: invitación + código de activación, con registro público cerrado

- **Estado:** Aceptado
- **Fecha:** 2026-09-09
- **Decide:** Producto / RRHH, con recomendación del equipo técnico
- **Fase:** 2 (invitación) · 6 (código de activación)

---

## Contexto

El sistema gestiona datos personales, salariales y documentos laborales. La
pregunta es cómo llega una persona a tener credenciales.

Restricciones que aplican:

- `User` y `Employee` son entidades distintas, con relación 0..1
  (ver [A.2.6](../architecture/01-analisis-de-dominio.md)). **Crear una cuenta
  nunca crea un empleado.**
- Parte de la plantilla (personal operativo) puede no tener correo corporativo.
- No existe todavía un proveedor de identidad corporativo confirmado.
- La verificación de correo es obligatoria en el diseño de autenticación.

---

## Alternativas consideradas

### A. Invitación por correo iniciada por RRHH

RRHH crea el `Employee` e invita; la persona recibe un token firmado de un solo
uso con el que fija su contraseña y verifica su correo en un paso.

- **A favor:** ninguna cuenta existe sin una decisión explícita de RRHH; trazable
  de punta a punta; la verificación de correo sale gratis; reutiliza mecanismo
  probado de Django.
- **En contra:** requiere que la persona tenga correo.
- **Costo de revertir:** bajo.

### B. Contraseña temporal entregada en mano

RRHH genera una contraseña aleatoria y la entrega impresa o presencialmente;
`must_change_password` fuerza el cambio en el primer acceso.

- **A favor:** cubre a quien no tiene correo.
- **En contra:** un secreto que **es** la credencial viaja en claro por un canal
  que el sistema no controla y que puede quedar archivado en papel indefinidamente.
- **Costo de revertir:** bajo.

### C. Código de activación de un solo uso

Igual que B, pero lo que se entrega **no es una contraseña**: es un código de
alta entropía, guardado solo como hash, con expiración y un único uso, que
únicamente sirve para activar la cuenta.

- **A favor:** si el papel se pierde, el atacante obtiene un token revocable y
  caducado, no una credencial permanente. Se puede revocar y reemitir. Queda
  auditado quién lo emitió y cuándo se canjeó.
- **En contra:** añade una entidad y un endpoint público que hay que proteger
  (límite de tasa, respuesta indistinguible).
- **Costo de revertir:** bajo.

### D. Auto-registro validando datos contra RRHH

La persona se registra sola demostrando conocer `employee_code`, DPI y fecha de
nacimiento.

- **Rechazada.** Convierte un endpoint sin autenticar en un **oráculo de validez
  de números de identificación**, y con fuerza bruta sobre fechas de nacimiento
  permite apoderarse de la cuenta de un tercero. Sustituir la PII por un secreto
  con entropía real la convierte, exactamente, en la alternativa C.

### E. Auto-registro con dominio de correo permitido + aprobación

Cualquiera con una dirección del dominio corporativo se registra y queda
pendiente de aprobación.

- **Rechazada.** Traslada el control de acceso al control del dominio de correo:
  buzones compartidos, cuentas de personal externo o de exempleados no dados de
  baja bastarían para entrar. Además genera una cola de solicitudes pendientes
  que en la práctica nadie revisa.

### F. SSO corporativo (OIDC / SAML)

Delegar la autenticación a Google Workspace o Microsoft Entra ID.

- **A favor:** resuelve de raíz el ciclo alta/traslado/baja, aporta MFA sin
  escribir código y elimina el almacenamiento de contraseñas.
- **En contra:** no hay IdP confirmado hoy; añade dependencia y configuración por
  entorno; introduce fricción en desarrollo local; y no elimina el vínculo
  `User ↔ Employee`, que sigue siendo manual.
- **Diferida**, no rechazada. Ver ADR-017.

---

## Decisión

**Se adopta A + C, y el registro público queda cerrado en todos los escenarios.**

1. **Fase 2 — invitación por correo (A).** Es el único mecanismo implementado.
   El alcance de la fase son cuentas de RRHH y jefaturas, colectivo que dispone
   de correo corporativo, por lo que el camino C no tiene usuarios todavía.
2. **Fase 6 — código de activación (C).** Se implementa cuando entra la plantilla
   general con el portal de autoservicio de ausencias. Se especifica ahora para
   que el modelo de datos y el flujo estén decididos, pero **no se construye
   antes de tener usuarios reales** (regla 56).
3. **Se descartan B, D y E** por los motivos anteriores. B queda cubierta por C,
   que es estrictamente mejor con el mismo costo operativo.
4. **F se difiere** a ADR-017, sin bloquear nada: elegir `django-allauth` mantiene
   la puerta abierta sin cambiar de librería.

### Cómo se cierra el registro

Dos mecanismos a la vez, deliberadamente redundantes:

- `ACCOUNT_ADAPTER` propio con `is_open_for_signup(request) → False`.
- Las rutas de `signup` no se incluyen en el enrutamiento.

Ninguno de los dos basta solo: retirar la URL no protege si una actualización de
allauth la reintroduce; el adaptador solo deja una ruta enlazada que responde
error.

### Identidad de acceso de quien no tiene correo corporativo

El código de activación resuelve el **arranque** de la identidad, no la
identidad en sí: `email` sigue siendo `USERNAME_FIELD`. Durante el canje, la
persona declara un correo (personal si no tiene corporativo) que se verifica por
el mecanismo habitual.

Consecuencia aceptada: un correo personal como identidad de acceso queda fuera
del control de la organización — la cuenta debe desactivarse explícitamente al
terminar el contrato, cosa que el sistema ya hace.

Caso residual sin solución en este ADR: la persona que no tiene ningún correo ni
posibilidad de obtenerlo **no tiene cuenta**; RRHH opera en su nombre. Si ese
colectivo resulta significativo, habrá que reabrir la decisión sobre
`USERNAME_FIELD` — y hacerlo **antes** de la Fase 6, porque cambiarlo después de
las migraciones es caro.

---

## Consecuencias

### Positivas

- Ninguna cuenta existe sin una decisión explícita y auditada de RRHH.
- No existe ningún endpoint sin autenticar que valide datos personales.
- Un secreto de activación extraviado es revocable y caduca; una contraseña
  entregada en papel, no.
- La Fase 2 se reduce: sin flujo de código, sin altas masivas.

### Negativas aceptadas

- RRHH asume la carga operativa de invitar una por una. Con el alcance de la
  Fase 2 (decenas de cuentas) es asumible; al llegar la plantilla completa habrá
  que ofrecer alta por lotes.
- La Fase 6 añade una entidad y un endpoint público que hay que proteger.
- Sin SSO, las contraseñas se almacenan localmente y la MFA queda pendiente
  (Fase 9).

### Qué habría que hacer para revertirla

Abrir el registro exigiría reintroducir las rutas de allauth, un adaptador
permisivo y un mecanismo de verificación de pertenencia a la organización — es
decir, volver a las alternativas D o E, ya rechazadas. La reversión realista es
avanzar hacia F.

---

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| `GET /accounts/signup/` responde 404 | `tests/security/test_url_coverage.py::test_signup_route_is_closed` ✅ |
| `is_open_for_signup` devuelve `False` | `...::test_adapter_reports_signup_as_closed` ✅ |
| Un `POST` directo al endpoint no crea usuario | `...::test_signup_post_creates_nothing` ✅ |
| Toda creación de `User` emite `USER_CREATE` con actor no nulo | `apps/accounts/tests/test_services.py::test_invite_is_audited` ✅ |
| El enlace de invitación es de un solo uso | `apps/accounts/tests/test_password_flows.py::test_reset_link_is_single_use` ✅ |
| El código de activación se almacena solo como hash | Test que verifica que el valor en claro no está en la base |
| Un código canjeado, revocado o caducado se rechaza con respuesta indistinguible | Tests de la Fase 6 |
| El canje respeta el límite de tasa por IP | Test de la Fase 6 |
