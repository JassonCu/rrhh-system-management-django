# ADR-023 — Expediente documental: archivo privado, nombre generado y archivado en vez de borrado

- **Estado:** Aceptado
- **Fecha:** 2026-09-19
- **Decide:** Equipo técnico, con el negocio en la regla de archivado
- **Fase:** 7

---

## Contexto

Los documentos de RRHH —contratos firmados, constancias, expedientes médicos—
son de los datos más sensibles del sistema. La Fase 0 ya había fijado la cadena
de validación (§K.4); al construir la fase quedaban tres decisiones que el
diseño no cerraba y que son caras de revertir: **dónde viven los archivos**,
**qué nombre llevan** y **qué pasa cuando alguien se equivoca al subirlos**.

## Decisiones

### 1. Los archivos viven en el sistema de archivos, tras la aplicación

`FileField` sobre `MEDIA_ROOT`, que está **fuera** del árbol servido por el
servidor web. La única forma de llegar a un archivo es una vista que autentica,
autoriza, comprueba confidencialidad y **audita antes de entregar**.

- **Por qué no almacenamiento de objetos (S3 y similares) hoy:** añade una
  dependencia y una cuenta que administrar para un volumen que cabe en disco, y
  las URLs firmadas mueven la autorización fuera de Django, justo donde ya
  vive toda la del sistema.
- **Cómo se cambia mañana:** `FileField` con otro `Storage`. La vista no cambia
  porque nunca construye rutas públicas.
- **En producción la entrega se delega** al servidor web con `X-Accel-Redirect`
  o `X-Sendfile`, manteniendo la autorización en Django: una línea, porque la
  vista ya es el único camino.

### 2. El nombre del archivo lo genera el sistema

Ruta `documents/<public_id del empleado>/<uuid4>.<extensión validada>`. El
nombre que subió la persona se guarda aparte, en `original_filename`, y solo se
usa para **mostrarlo** y para el `Content-Disposition` de la descarga, ya
saneado.

- **Por qué:** el nombre es la vía clásica de *path traversal* y de inyección de
  cabeceras. Si nunca toca el sistema de archivos, esos ataques no tienen dónde
  entrar. La función que arma la ruta **ignora a propósito** el nombre que le
  pasa Django, y lo dice en un comentario para que nadie lo «arregle».

### 3. Un documento no se borra: se archiva, con motivo

`is_active = False` más `archived_reason`, auditado. El permiso
`delete_employeedocument` **no se otorga a nadie** y el modelo ni siquiera lo
declara; existe `archive_document` en su lugar.

- **Por qué:** un expediente es prueba. Un borrado por error —o uno conveniente
  justo antes de un conflicto laboral— no debe ser posible desde la aplicación.
- **El archivo en disco se conserva**, no solo la fila.
- **El índice único por checksum es parcial** (`is_active = TRUE`): archivar un
  documento mal subido libera el checksum para volver a subirlo corregido. Sin
  esa condición, equivocarse una vez bloqueaba el trámite para siempre.

### 4. Ver que un documento existe y poder abrirlo son permisos distintos

Un tipo marcado `is_sensitive` aparece en el expediente para todo el que tenga
alcance sobre la ficha, pero solo lo abre quien tiene
`view_sensitive_document` —administración de RRHH y auditoría—, ni siquiera la
propia persona cuando es un documento confidencial de RRHH (§J.2).

- **Por qué:** RRHH necesita poder **pedir** un documento que no puede leer, y
  esconder su existencia haría imposible gestionar el expediente. Lo que se
  protege es el contenido.

## Consecuencias

### Positivas
- Ningún archivo es alcanzable sin pasar por la autorización y la bitácora.
- Los ataques por nombre de archivo quedan sin superficie.
- Nadie puede hacer desaparecer un documento del expediente.

### Negativas aceptadas
- **Cada descarga consume proceso de la aplicación** hasta que se delegue al
  servidor web.
- **`MEDIA_ROOT` hay que respaldarlo aparte:** no está en el volcado de la base,
  y un expediente perdido no se recupera de ahí.
- **Sin antivirus** (§K.4, paso 7): la firma y la allowlist reducen el riesgo,
  no lo eliminan. Se revisa en la Fase 9.
- **La retención no se aplica sola:** `retention_years` se captura pero ningún
  proceso purga nada. Es una decisión de negocio pendiente, y cuando se tome
  exigirá su propio comando y su propia revisión.
