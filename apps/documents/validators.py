"""Cadena de validación de subida (§K.4), **en este orden**.

El orden importa: primero lo barato y lo que evita leer el archivo (tamaño),
después lo declarado (extensión, `content_type`) y al final lo que obliga a
abrirlo (firma y checksum). Nada de lo que viene del cliente se cree: el nombre
se descarta, el `content_type` se comprueba pero no decide, y lo que manda es el
contenido real.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from apps.core.exceptions import ConflictError
from apps.documents.constants import (
    EXPECTED_CONTENT_TYPES,
    MAGIC_SIGNATURES,
    MAX_SIZE_MB,
    SIGNATURE_BYTES,
)

BYTES_PER_MB = 1024 * 1024

#: Tamaño de bloque al calcular el checksum: no se carga el archivo en memoria.
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class CheckedUpload:
    """Lo que la cadena deja listo para guardar. Nada de esto viene del cliente."""

    extension: str
    size_bytes: int
    checksum: str
    original_filename: str
    content_type: str


def _extension_of(filename: str) -> str:
    """Extensión declarada en el nombre, sin rutas ni trucos.

    Se parte por los dos separadores a propósito: un nombre como
    `..\\..\\evil.pdf` no debe dejar rastro de ruta en ninguna parte.
    """
    tail = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[-1].lower() if "." in tail else ""


def safe_display_name(filename: str) -> str:
    """Nombre para **mostrar y descargar**, nunca para escribir en disco.

    Quita rutas, comillas y saltos de línea: sin esto, un nombre con `\\r\\n`
    permitiría inyectar cabeceras en la respuesta de descarga (§K.4).
    """
    tail = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(char for char in tail if char.isprintable() and char not in '"\r\n;')
    return cleaned.strip() or "documento"


def check_upload(upload, document_type) -> CheckedUpload:
    """Aplica la cadena completa o levanta `ConflictError` con su motivo."""
    # 1. Tamaño, antes de leer nada.
    size = getattr(upload, "size", 0) or 0
    if size <= 0:
        raise ConflictError("empty_file")
    limit_mb = min(document_type.max_size_mb, MAX_SIZE_MB)
    if size > limit_mb * BYTES_PER_MB:
        raise ConflictError("file_too_large", limit=limit_mb)

    # 2. Extensión contra la allowlist del tipo.
    extension = _extension_of(getattr(upload, "name", "") or "")
    allowed = document_type.extensions
    if not allowed:
        raise ConflictError("type_without_formats")
    if extension not in allowed:
        raise ConflictError("extension_not_allowed", allowed=", ".join(allowed))

    # 3. Contenido real: la firma manda sobre lo que diga el nombre.
    head = _read_head(upload)
    if not any(head.startswith(signature) for signature in MAGIC_SIGNATURES[extension]):
        raise ConflictError("content_does_not_match_extension", extension=extension)

    # 4. `content_type` declarado: se comprueba, no se confía.
    declared = (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
    if declared and declared not in EXPECTED_CONTENT_TYPES[extension]:
        raise ConflictError("content_type_mismatch", extension=extension)

    # 5. El nombre no se usa como ruta: solo se guarda para mostrarlo.
    original = safe_display_name(getattr(upload, "name", "") or "")[:255]

    # 6. Checksum, leyendo por bloques.
    return CheckedUpload(
        extension=extension,
        size_bytes=size,
        checksum=_checksum(upload),
        original_filename=original,
        content_type=declared[:100],
    )
    # 7. Antivirus: fuera de esta fase, documentado como riesgo aceptado (§K.4).


def _read_head(upload) -> bytes:
    upload.seek(0)
    head = upload.read(SIGNATURE_BYTES)
    upload.seek(0)
    return head


def _checksum(upload) -> str:
    digest = hashlib.sha256()
    upload.seek(0)
    for chunk in iter(lambda: upload.read(CHUNK_SIZE), b""):
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()
