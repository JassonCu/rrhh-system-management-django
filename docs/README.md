# Documentación — Sistema de Gestión de RRHH

**Estado del proyecto: Fases 0 a 7 cerradas.** Siguiente: Fase 8 — Nómina, que requiere análisis de dominio propio antes de implementarse. El diseño de la Fase 0
está aprobado y sirve de contrato: todo cambio de esquema debe actualizar estos
documentos en el mismo commit.

---

## Índice

### Arquitectura

| Documento | Contenido |
|---|---|
| [01 — Análisis del dominio](architecture/01-analisis-de-dominio.md) | Supuestos, contextos delimitados, entidades, agregados, relaciones, cardinalidades y 60 reglas de negocio numeradas |
| [08 — Arquitectura Django](architecture/08-arquitectura-django.md) | Estructura de directorios, capas y responsabilidades, reglas de dependencia entre apps, plantillas, configuración |
| [14 — Internacionalización](architecture/14-internacionalizacion.md) | i18n de interfaz vs. de datos, configuración, reglas por capa (modelos, formularios, vistas, plantillas), formatos de Guatemala, flujo de traducción y pruebas |

### Base de datos

| Documento | Contenido |
|---|---|
| [02 — Modelo relacional](database/02-modelo-relacional.md) | Cada relación con PK, FK, claves candidatas y constraints |
| [03 — Dependencias funcionales](database/03-dependencias-funcionales.md) | DF por entidad, claves candidatas, dependencias evitadas |
| [04 — Normalización y anomalías](database/04-normalizacion.md) | Demostración 1NF→5NF, redundancia justificada, análisis de anomalías |
| [05 — ERD](database/05-erd.md) | Diagramas Mermaid: vista global, por contexto y máquina de estados |
| [06 — Diccionario de datos](database/06-diccionario-de-datos.md) | Atributos, tipos, nulabilidad, reglas y clasificación de la información |
| [07 — Integridad e índices](database/07-integridad-e-indices.md) | `on_delete` por FK, soft delete, inventario de constraints, índices con su consulta justificante, preparación para PostgreSQL |

### Seguridad

| Documento | Contenido |
|---|---|
| [09 — Autenticación](security/09-autenticacion.md) | django-allauth, registro cerrado, contraseñas, sesiones, eventos auditados |
| [10 — Autorización](security/10-autorizacion.md) | Roles, matriz de permisos, alcance a nivel de objeto, prevención de escalada, tests |
| [11 — Seguridad](security/11-seguridad.md) | Ajustes por entorno, CSP, OWASP, seguridad de archivos, logging, errores, secretos |
| [Revisión de la Fase 2](security/revision-fase-2.md) | Checklist §K.9 aplicado: 4 hallazgos corregidos y 2 desviaciones aceptadas |
| [Revisión de la Fase 3](security/revision-fase-3.md) | Exposición latente de contactos personales corregida antes de la Fase 4 |
| [Revisión de la Fase 4](security/revision-fase-4.md) | Separación de funciones: nadie modifica su propia relación laboral |
| [Revisión de la Fase 5](security/revision-fase-5.md) | Dos errores de cálculo corregidos antes de que llegaran a la planilla |
| [Revisión de la Fase 6](security/revision-fase-6.md) | Nadie ajusta su propio saldo; una ausencia aprobada ya no genera faltas de asistencia |
| [Revisión de la Fase 7](security/revision-fase-7.md) | Cadena de validación de archivos completa: ejecutable renombrado, path traversal, tamaño, descarga no autorizada y acceso directo a `/media/` |
| [Revisión del módulo de reportes](security/revision-reportes.md) | Inyección de fórmulas en Excel, marcado sin escapar en el PDF y un documento archivado que seguía descargándose |

### Desarrollo

| Documento | Contenido |
|---|---|
| [12 — DevSecOps](development/12-devsecops.md) | Dependencias, Ruff, pytest, cobertura, pre-commit, GitHub Actions, criterios de aceptación |
| [13 — Roadmap](development/13-roadmap.md) | Fases 0 a 9 con entregables y criterios de cierre |
| [15 — Plan UX/UI](ux/15-plan-ux-ui.md) | Diagnóstico, roles y tareas, arquitectura de información, patrones, sistema de diseño, accesibilidad WCAG 2.2 AA y entregas UX-0 a UX-5 |
| [16 — Identidad de marca](ux/16-identidad-de-marca.md) | Ceiba RH: nombre, logotipo y reglas de uso, paleta con contrastes verificados, tipografía, voz y tono |
| [17 — Patrones de las Fases 5 a 8](ux/17-patrones-fases-5-8.md) | Marcaje, bandeja de aprobaciones, calendario de ausencias, subida de documentos y recibo de nómina: patrones, accesibilidad y pruebas exigidas antes de abrir cada fase |

### Decisiones

| Documento | Contenido |
|---|---|
| [ADR — índice y plantilla](decisions/README.md) | 21 decisiones catalogadas; **18 aceptadas y escritas**, el resto se redacta al abrir su fase |

Aceptados: [001 Monolito modular](decisions/ADR-001-monolito-modular.md) ·
[002 SQLite inicial](decisions/ADR-002-sqlite-inicial.md) ·
[003 Migración a PostgreSQL](decisions/ADR-003-migracion-a-postgresql.md) ·
[004 Alta de cuentas](decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md) ·
[005 Autorización por selectores](decisions/ADR-005-autorizacion-por-selectores.md) ·
[006 Normalización BCNF](decisions/ADR-006-normalizacion-objetivo-bcnf.md) ·
[007 CSP estricta](decisions/ADR-007-csp-estricta-con-nonce.md) ·
[008 Auditoría append-only](decisions/ADR-008-auditoria-append-only.md) ·
[009 services/selectors](decisions/ADR-009-capas-services-y-selectors.md) ·
[010 Company desde el inicio](decisions/ADR-010-entidad-company-desde-el-inicio.md) ·
[011 Puesto por departamento](decisions/ADR-011-position-pertenece-a-departamento.md) ·
[012 Estado laboral materializado](decisions/ADR-012-estado-laboral-materializado.md) ·
[013 Argon2](decisions/ADR-013-argon2-como-hasher.md) ·
[014 Historial temporal](decisions/ADR-014-historial-temporal.md) ·
[015 Libro de ausencias](decisions/ADR-015-ledger-de-ausencias.md) ·
[018 Internacionalización](decisions/ADR-018-estrategia-de-internacionalizacion.md) ·
[019 Acceso móvil](decisions/ADR-019-acceso-movil.md) ·
[020 CSS propio](decisions/ADR-020-css-propio.md) ·
[021 Reglas de asistencia](decisions/ADR-021-reglas-de-asistencia.md) ·
[022 Reglas de ausencias](decisions/ADR-022-reglas-de-ausencias.md) ·
[023 Expediente documental](decisions/ADR-023-expediente-documental.md)

---

## Cómo leer este diseño

1. Empieza por **[01 — Análisis del dominio](architecture/01-analisis-de-dominio.md)**;
   en particular por §A.0, que lista los supuestos que hay que confirmar.
2. Sigue con el **[ERD](database/05-erd.md)** para tener la foto completa.
3. Profundiza en **[04 — Normalización](database/04-normalizacion.md)** si quieres
   ver por qué el modelo tiene esta forma y no otra.
4. Las decisiones más discutibles están señaladas en el texto y recogidas en el
   [índice de ADR](decisions/README.md).

---

## Qué falta para cerrar la Fase 0

- [x] ~~S-02 — multi-empresa~~ → **se incluye `Company` desde la Fase 1** (ADR-010).
- [x] ~~S-04 — alta de cuentas y registro público~~ → resuelto en
      [ADR-004](decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md):
      invitación por correo (Fase 2) + código de activación (Fase 6).
- [x] ~~Idioma de los `msgid`~~ → **inglés**, con catálogo `es_GT` (ADR-018).
- [ ] Confirmar los supuestos restantes **S-01, S-03, S-05 … S-08** (§A.0).
- [ ] Responder las cuatro decisiones abiertas de dominio (§A.0).
- [x] ~~`Position` global vs. por departamento~~ → **pertenece a un departamento**
      ([ADR-011](decisions/ADR-011-position-pertenece-a-departamento.md)).

Los supuestos restantes no bloquean la Fase 1; sí condicionan las Fases 3 en adelante.
