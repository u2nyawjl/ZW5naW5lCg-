from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class VTStatus(StrEnum):
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    HARMLESS = "harmless"
    UNKNOWN = "unknown"        # VT no ha visto nunca este hash: el caso normal de un doc privado
    SKIPPED = "skipped"        # sin API key configurada
    ERROR = "error"            # cuota agotada, red caída, key inválida


class Decision(StrEnum):
    ALLOW = "allow"    # se extrae el texto
    HOLD = "hold"      # en cuarentena, esperando liberación manual
    BLOCK = "block"    # malicioso o ejecutable: ningún parser lo toca


class VTVerdict(BaseModel):
    status: VTStatus
    malicious: int = 0
    suspicious: int = 0
    harmless: int = 0
    total_engines: int = 0
    permalink: str | None = None
    detail: str | None = None

    @property
    def is_dangerous(self) -> bool:
        return self.status in (VTStatus.MALICIOUS, VTStatus.SUSPICIOUS)


class FileReport(BaseModel):
    filename: str
    source: str = "manual"                 # whatsapp | email | manual
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    size_bytes: int
    sha256: str
    md5: str

    mime: str                              # detectado con libmagic, no por la extensión
    declared_extension: str
    extension_mismatch: bool = False       # "factura.pdf" que en realidad es un ejecutable

    virustotal: VTVerdict
    decision: Decision
    reason: str

    quarantine_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    text_chars: int = 0
    warnings: list[str] = Field(default_factory=list)
