"""Catálogos y límites del expediente documental (§K.4).

Los **valores** son ASCII estable y nunca se traducen (§O.3.1).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

#: Tope global de tamaño, por encima de lo que diga cualquier tipo (§K.4).
MAX_SIZE_MB = 25

#: Extensiones admitidas en todo el sistema. **Allowlist**, nunca denylist: una
#: lista de lo prohibido siempre se queda corta.
ALLOWED_EXTENSIONS: tuple[str, ...] = ("pdf", "png", "jpg", "jpeg", "docx")

#: Firmas reales de cada formato («magic bytes»). Un `.pdf` que empieza con `MZ`
#: es un ejecutable renombrado, y aquí se cae.
#:
#: Se usa una tabla propia en vez de `python-magic` a propósito: esa biblioteca
#: necesita `libmagic`, que en Windows es una fricción de instalación
#: innecesaria para cinco formatos (§K.4).
MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    # Un .docx es un contenedor ZIP: firma de ZIP, incluida la de archivo vacío.
    "docx": (b"PK\x03\x04", b"PK\x05\x06"),
}

#: Bytes que basta leer para reconocer cualquiera de las firmas anteriores.
SIGNATURE_BYTES = 8

#: `content_type` que un cliente honesto declararía para cada extensión. Se
#: comprueba, pero **no se confía**: lo envía el cliente (§K.4, paso 4).
EXPECTED_CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    "pdf": ("application/pdf",),
    "png": ("image/png",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    ),
}

#: Longitud de un SHA-256 en hexadecimal.
CHECKSUM_LENGTH = 64

#: Ventana de aviso de vencimiento, igual que la de contratos.
EXPIRY_WARNING_DAYS = 30

#: Años de retención máximos que admite un tipo. Más que eso es un error de
#: captura, no una política.
MAX_RETENTION_YEARS = 50


class DocumentStatus(models.TextChoices):
    """Estado de un documento **para la interfaz**; en la base es `is_active`."""

    ACTIVE = "ACTIVE", _("Active")
    ARCHIVED = "ARCHIVED", _("Archived")
    EXPIRED = "EXPIRED", _("Expired")
    EXPIRING = "EXPIRING", _("Expiring soon")
