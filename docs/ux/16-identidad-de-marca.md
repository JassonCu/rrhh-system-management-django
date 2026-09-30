# 16 — Identidad de marca: Ceiba RH

- **Estado:** Aceptado (P-1 del [plan UX/UI](15-plan-ux-ui.md))
- **Fecha:** 2026-09-14
- **Recursos:** `static/img/brand/` y `static/img/favicon.svg`

> **Antes de usar el nombre en producción** hay que verificar su disponibilidad
> como marca registrada en el Registro de la Propiedad Intelectual de Guatemala
> y en los países donde se comercialice. Este documento no sustituye esa
> búsqueda.

---

## 1. Nombre

**Ceiba RH**: *ceiba* en minúsculas en el logotipo; «Ceiba RH» en texto corrido.

La ceiba es el **árbol nacional de Guatemala**. Se eligió porque su forma cuenta lo
que hace el sistema:

| Parte del árbol | En el sistema |
|---|---|
| Raíces | Los expedientes: datos que sostienen todo lo demás y no deben perderse |
| Tronco y ramas | La estructura: departamentos, puestos, jefaturas |
| Copa | Las personas y sus equipos |
| Longevidad | El historial: nada se sobrescribe ([ADR-014](../decisions/ADR-014-historial-temporal.md)) |

**El nombre no se traduce.** Es una marca, no texto de interfaz: se define una
sola vez en `settings.PRODUCT_NAME` y las plantillas lo leen de ahí, sin `{% translate %}`.

## 2. Logotipo

### 2.1 Construcción

El isotipo es una ceiba geométrica sobre un cuadrado redondeado:

- **Tronco y dos ramas** en blanco: la estructura organizacional, que también
  se lee como un organigrama.
- **Tres nodos** formando la copa: personas conectadas.
- **El nodo superior en maíz** (`#E8A92B`): quien dirige. Es el único acento
  cálido de la marca y no se usa para nada más en el logotipo.
- **Suelo**: una línea horizontal, las raíces.

### 2.2 Versiones

| Archivo | Uso |
|---|---|
| `brand/ceiba-mark.svg` | Isotipo solo: barra de navegación, avatar de la app, espacios cuadrados |
| `brand/ceiba-logo.svg` | Logotipo horizontal sobre fondos claros |
| `brand/ceiba-logo-inverse.svg` | Logotipo horizontal sobre jade oscuro o fotografía |
| `favicon.svg` | Pestaña del navegador: versión simplificada con trazos más gruesos, legible a 16 px |

### 2.3 Reglas de uso

- **Tamaño mínimo:** isotipo 20 px; logotipo horizontal 96 px de ancho.
- **Área de respeto:** alrededor del logotipo, un margen igual a un tercio de la
  altura del isotipo.
- **No** cambiar los colores, rotar, deformar, añadir sombras ni colocarlo sobre
  fondos con contraste menor de 3:1.
- **No** separar el nodo dorado ni usarlo como viñeta decorativa.

### 2.4 Nota técnica

El texto del logotipo horizontal usa la fuente del sistema (`system-ui`), así que
varía ligeramente entre Windows, macOS y Android. **Es aceptable dentro de la
aplicación.** Para piezas impresas o de terceros (presentaciones, papelería) se
debe convertir el texto a trazos con un editor vectorial y guardar esa versión
aparte. Los SVG no contienen scripts ni referencias externas: lo verifica
`tests/test_brand.py`, porque se sirven bajo la CSP.

## 3. Color

Todos los pares de texto cumplen **WCAG 2.2 AA** (contraste mínimo 4,5:1). Las
cifras están calculadas, no estimadas.

### 3.1 Marca

| Token | Hex | Uso | Contraste verificado |
|---|---|---|---|
| `jade-900` | `#083A32` | Panel de marca, fondos oscuros | Blanco encima: 12,64:1 |
| `jade-800` | `#0B574A` | Hover del botón primario | Blanco encima: 8,48:1 |
| `jade-700` | `#0F6E5C` | **Color primario**: botones, enlaces, foco | Sobre blanco: 6,17:1 · sobre `jade-50`: 5,47:1 |
| `jade-50` | `#E8F4F1` | Fondos de selección y resaltado | — |
| `maiz-400` | `#E8A92B` | Acento: nodo del logotipo, detalles sobre fondo oscuro | Sobre `jade-900`: 6,10:1 · **nunca como texto sobre blanco** |
| `maiz-700` | `#8A5A00` | Acento como texto sobre fondo claro | Sobre blanco: 5,93:1 |

### 3.2 Neutros

| Token | Hex | Uso | Contraste verificado |
|---|---|---|---|
| `tinta` | `#17201E` | Texto principal | Sobre fondo: 15,44:1 |
| `gris-600` | `#5B6763` | Texto secundario | Sobre blanco: 5,89:1 · sobre fondo: 5,46:1 |
| `gris-400` | `#8A9692` | Borde de controles de formulario | Sobre blanco: 3,06:1 (mínimo para controles) |
| `gris-200` | `#D5DEDB` | Separadores y bordes de tarjetas | Decorativo |
| `fondo` | `#F4F7F6` | Fondo de página | — |
| `superficie` | `#FFFFFF` | Tarjetas, tablas, formularios | — |

### 3.3 Estados

Distintos del jade a propósito: un «Activo» no debe confundirse con un botón.

| Estado | Texto | Fondo | Contraste |
|---|---|---|---|
| Éxito / Activo | `#1F6B35` | `#E6F4EA` | 5,76:1 |
| Aviso / Suspendido | `#7A4F00` | `#FFF3DC` | 6,49:1 |
| Error | `#A3261D` | `#FDECEA` | 6,44:1 |
| Información / Borrador | `#1D5FA8` | `#E7F0FA` | 5,61:1 |
| Neutro / Terminado | `#4A5552` | `#ECEFEE` | 6,69:1 |

## 4. Tipografía

- **Familia:** `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
  Sin fuentes de Google ni CDN: la CSP solo admite `font-src 'self'`, y la
  fuente del sistema carga al instante en móviles de gama baja.
- **Opción futura:** una fuente propia **autoalojada** en `static/fonts/` es
  compatible con la CSP. Se decidiría con una prueba de rendimiento en móvil.
- **Escala:** 12 · 14 · 16 (base) · 20 · 24 · 32 px.
- **Pesos:** 400 texto, 600 etiquetas y botones, 700 títulos.
- **Cifras tabulares** (`font-variant-numeric: tabular-nums`) en tablas, importes
  y fechas, para que las columnas se alineen.

## 5. Voz y tono

| Principio | Así | Así no |
|---|---|---|
| Claro | «Dar de baja a Ana Pérez» | «Ejecutar terminación de relación laboral» |
| Respetuoso (usted) | «Revise la fecha de inicio» | «¡Ups! Algo salió mal» |
| Explica el motivo | «No puede modificar su propio contrato» | «Acción no permitida» |
| Sin jerga técnica | «Esta información es confidencial» | «403 Forbidden» |
| Sereno | Los errores no usan exclamaciones ni humor | — |

Los temas de RRHH (bajas, salarios, sanciones) son sensibles para quien los lee:
**ningún mensaje hace bromas**.

## 6. Iconografía e imágenes

- **Iconos:** trazo de 2 px, esquinas redondeadas, 20 px en interfaz, en un
  *sprite* SVG local (`static/img/icons.svg`). Sin librerías de iconos por CDN.
- **Fotografías de personas:** no se usan en la marca. En la aplicación, las
  fichas usan **avatares de iniciales** hasta que la Fase 7 permita subir fotos
  con su propio control de acceso.
- **Ilustraciones:** formas geométricas derivadas del isotipo (círculos y
  líneas), como las del panel de acceso.

## 7. Aplicaciones

| Soporte | Aplicación |
|---|---|
| Pantalla de acceso | Panel `jade-900 → jade-700` con el isotipo, nombre y propuesta de valor |
| Barra de navegación | Isotipo de 28 px + «Ceiba RH» |
| Pestaña del navegador | `favicon.svg` · título «Página · Ceiba RH» |
| Correos del sistema | Asunto con prefijo `[Ceiba RH]` |
| App móvil (futura, [ADR-019](../decisions/ADR-019-acceso-movil.md)) | Isotipo como icono de la app sobre `jade-800` |
| Documentos PDF (Fase 7–8) | Logotipo horizontal en la cabecera, colores neutros para imprimir en blanco y negro |
