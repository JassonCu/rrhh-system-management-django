# ADR-020 — Sistema de diseño con CSS propio, sin framework CSS

- **Estado:** Aceptado
- **Fecha:** 2026-09-14
- **Decide:** Equipo técnico
- **Fase:** UX-1

---

## Contexto

La entrega UX-1 del [plan UX/UI](../ux/15-plan-ux-ui.md) crea la estructura de
la aplicación y sus componentes. Hay que decidir con qué se escriben los estilos.
Condicionantes:

- **CSP estricta** sin `unsafe-inline` ([ADR-007](ADR-007-csp-estricta-con-nonce.md)):
  nada de `style=""`, ni scripts en línea, ni recursos de CDN.
- **Sin paso de compilación de frontend**: el proyecto no tiene Node, y añadirlo
  solo para CSS introduce una cadena de suministro nueva.
- **Volumen moderado:** unas 40 plantillas y una docena de componentes.
- **Identidad propia** ([16](../ux/16-identidad-de-marca.md)): tokens de color y
  tipografía definidos y con contraste verificado.

## Alternativas consideradas

### A. Bootstrap (CSS precompilado, autoalojado)
- **A favor:** componentes listos y conocidos.
- **En contra:** ~200 KB de CSS casi sin usar; su JS de componentes no se
  necesita; personalizar los tokens sin Sass implica pisar estilos. El aspecto
  «Bootstrap» diluye la identidad propia.

### B. Tailwind CSS
- **A favor:** productividad y tamaño final pequeño.
- **En contra:** exige un paso de compilación (Node o binario) para purgar
  clases; las plantillas se llenan de clases utilitarias, más difíciles de
  revisar en busca de problemas de seguridad y de accesibilidad.

### C. CSS propio con capas en cascada *(elegida)*
Un único `static/css/main.css` con `@layer tokens, base, layout, components,
pages, utilities`, componentes con nombres BEM ligeros (`page-header__title`,
`button--primary`) e iconos en un *sprite* SVG local.

- **A favor:** cero dependencias ni compilación; cumple la CSP por construcción;
  los tokens de la marca son la fuente única; las capas hacen explícito qué
  estilo gana, sin guerras de especificidad.
- **En contra:** hay que escribir y mantener los componentes; sin la
  documentación de un framework, el catálogo de componentes vive en el plan UX.

## Decisión

Se adopta **C**. Reglas:

1. **Una sola hoja** (`main.css`) mientras no supere un tamaño que lo justifique;
   dividirla después es barato.
2. **Tokens primero:** ningún componente usa un color, radio o espaciado literal
   si existe su token.
3. **Componentes por patrón** (plan UX/UI §5–6): una pantalla nueva reutiliza
   `page-header`, `card`, `table-scroll`, `badge`, `empty-state`, `form-card` y
   `form-actions` antes de inventar clases.
4. **Iconos** en `static/img/icons.svg` referenciados con `<use>` a través de
   `includes/icon.html`.
5. **Sin JavaScript obligatorio:** la barra lateral se pliega con `<details>`; el
   JS solo mejora.

## Consecuencias

### Positivas
- Ninguna dependencia nueva que auditar con `pip-audit` o su equivalente de Node.
- La CSP no necesita excepciones.
- La identidad Ceiba RH se aplica desde los tokens, no sobreescribiendo un tema.

### Negativas aceptadas
- Los componentes complejos (selector de fechas avanzado, tablas ordenables,
  diálogos) hay que construirlos; se usan los controles nativos del navegador
  mientras sirvan.
- Sin versionado de estáticos: `STORAGES` usa `StaticFilesStorage`, así que tras
  cambiar el CSS el navegador puede servir la copia antigua (ocurrió al probar
  la marca). **Pendiente antes de producción:** pasar a
  `ManifestStaticFilesStorage`, que añade un hash al nombre de cada archivo.

### Qué habría que hacer para revertirla
Adoptar un framework implicaría reescribir las clases de todas las plantillas.
Coste medio: los patrones están centralizados en unos pocos includes y la
estructura HTML es semántica.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Sin estilos, scripts ni manejadores en línea | `tests/security/test_template_safety.py` |
| Toda página extiende una base común | `tests/test_app_shell.py::test_every_page_extends_a_base` |
| Toda tabla es accesible (`caption`, `th scope`) | `tests/test_app_shell.py::test_tables_are_accessible` |
| Todo icono usado existe en el sprite | `tests/test_app_shell.py::test_every_icon_used_exists_in_the_sprite` |
| Ningún SVG ejecuta scripts ni carga recursos externos | `tests/test_brand.py::test_svg_assets_are_inert` |
