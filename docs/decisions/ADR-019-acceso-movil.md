# ADR-019 — Acceso móvil: web responsive ahora, API para app nativa después

- **Estado:** Aceptado
- **Fecha:** 2026-09-14
- **Decide:** Producto, con análisis del equipo técnico
- **Fase:** UX-1 a UX-3 (web responsive) · Fase 10 (API y app móvil)

---

## Contexto

El producto confirmó dos hechos (P-2 del [plan UX/UI](../ux/15-plan-ux-ui.md)):

1. **Los empleados accederán desde el celular.** Es un requisito, no una mejora:
   el autoservicio (ver su contrato, y en fases futuras solicitar ausencias o
   consultar recibos) se usará sobre todo desde el móvil.
2. **Se contempla una app móvil nativa** en el futuro, que consumiría una API.

Hoy el sistema es un monolito Django con vistas y plantillas, **sin API**
([ADR-001](ADR-001-monolito-modular.md), que descartó una API REST desde el
inicio). Toda la lógica vive en `services` y `selectors`
([ADR-009](ADR-009-capas-services-y-selectors.md)), no en las vistas.

## Alternativas consideradas

### A. Solo web responsive
- **A favor:** sin superficie de ataque nueva; una sola interfaz que mantener.
- **En contra:** cierra la puerta a la app nativa (notificaciones push,
  marcaje de asistencia con geolocalización, uso sin conexión).

### B. API REST ahora y la web consumiéndola
- **A favor:** una única vía de acceso a los datos.
- **En contra:** reescribir las Fases 2–4, duplicar la protección CSRF/sesión
  con tokens, y abrir una superficie de ataque **antes** de que exista ningún
  cliente que la use. Es exactamente lo que ADR-001 rechazó.

### C. Web responsive ahora; API como segundo adaptador cuando exista la app *(elegida)*
- **A favor:** entrega valor móvil de inmediato; la API se añade sobre los mismos
  `services` y `selectors`, sin reescribir nada; no se expone una API sin cliente.
- **En contra:** exige disciplina hoy para que nada de lógica se escape a vistas o
  plantillas, porque la API no podría reutilizarla.

### D. PWA (web instalable) como sustituto de la app
- **Complementaria, no alternativa.** Un *manifest* y un icono permiten «instalar»
  la web en el móvil con coste casi nulo. Se evaluará en UX-3. No resuelve
  notificaciones fiables en iOS ni el uso sin conexión con datos sensibles.

## Decisión

Se adopta **C**, en dos etapas.

### Etapa 1 — Web responsive (entregas UX-1 a UX-3)

- El autoservicio (`Mi espacio`) y las vistas del `MANAGER` se diseñan
  **primero para móvil** (320 px); las pantallas de RRHH, para escritorio.
- Criterio de aceptación de cada pantalla: usable a 320 px de ancho sin
  desplazamiento horizontal de página.

### Etapa 2 — API y app móvil (Fase 10)

Restricciones que se fijan **ahora**, para que la API no nazca insegura:

| Tema | Decisión |
|---|---|
| Autenticación | **`allauth.headless`** en modo *app* (tokens de sesión). Ya es dependencia del proyecto (65.19.3) y reutiliza la política de acceso: registro cerrado (ADR-004), verificación de correo, límites de intentos y, en la Fase 9, MFA. **No** se implementa un sistema de tokens propio |
| Autorización | Cada vista de API usa **los mismos selectores de alcance** que la web. Un recurso fuera del alcance devuelve 404, igual que en la web (§J) |
| Identificadores | Solo `public_id` (UUID) en URLs y respuestas; nunca claves internas |
| Lógica | La API **no contiene lógica de negocio**: llama a `services`. Una regla que solo exista en la API es un defecto |
| Datos sensibles | Mismo filtrado: un salario sin `view_salary` no se serializa, no se «oculta» en el cliente |
| Versionado | Prefijo `/api/v1/`; un cambio incompatible crea `/api/v2/` |
| CORS | **Desactivado**: una app nativa no lo necesita. Si algún día hay un cliente web en otro origen, se decide con su propio análisis |
| Límites de uso | Por usuario y por IP en todos los endpoints de escritura y de autenticación |
| Auditoría | Los mismos eventos que la web, con el canal (`web` o `api`) en la metadata |
| Contrato | Esquema OpenAPI generado y versionado; pruebas de contrato en CI |
| Framework | **Se decide al abrir la Fase 10** entre Django REST Framework y django-ninja, con su propio ADR. Elegirlo hoy sería decidir sin requisitos |

## Consecuencias

### Positivas
- Acceso móvil real en cuanto terminen las entregas UX, sin esperar una app.
- Cero superficie de ataque nueva hasta que exista un cliente que la justifique.
- La inversión en `services`/`selectors` de las Fases 2–4 se reutiliza tal cual.

### Negativas aceptadas
- **Disciplina de capas obligatoria desde hoy.** Cualquier cálculo hecho en una
  vista o plantilla habrá que moverlo cuando llegue la API. Lo vigilan las
  pruebas de fronteras entre apps y la revisión de código.
- Hasta la Fase 10 **no hay** notificaciones push ni uso sin conexión.
- Dos adaptadores (web y API) que mantener cuando exista la app.

### Qué habría que hacer para revertirla
Pasar a A es trivial (no construir la Fase 10). Pasar a B implicaría reescribir la
web como cliente de la API: coste alto y sin beneficio mientras la web funcione.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Las vistas no importan modelos de otras apps ni contienen lógica de negocio | `tests/test_app_boundaries.py` y revisión de código |
| Cada pantalla de autoservicio es usable a 320 px | Criterio de cierre de UX-2 y UX-3 |
| Al abrir la Fase 10: cada endpoint tiene su prueba de alcance (IDOR) reutilizando la matriz §J.2 | Suite de la Fase 10 |
| Al abrir la Fase 10: `allauth.headless` con registro cerrado | Prueba equivalente a `test_signup_route_is_closed` sobre la API |
