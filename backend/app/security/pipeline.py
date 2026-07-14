"""Pipeline de ingesta segura.

El orden no es negociable: nada parsea un archivo antes de que VirusTotal se haya
pronunciado sobre su hash. Un PDF malicioso explota al parser, así que "extraer el
texto para ver qué es" es exactamente el error que este módulo existe para impedir.

    cuarentena → SHA-256 → VirusTotal → tipo real (libmagic) → decisión → metadata → texto
"""

from pathlib import Path

import magic

from app.core.events import Level, log_event
from app.extractors import csv as csv_x
from app.extractors import pdf as pdf_x
from app.extractors import pptx as pptx_x
from app.extractors import registry
from app.extractors import xlsx as xlsx_x
from app.security.hashing import md5_bytes, sha256_bytes
from app.security.models import Decision, FileReport, VTStatus, VTVerdict
from app.security.quarantine import store
from app.security.virustotal import VirusTotalClient


async def ingest_file(
    content: bytes,
    filename: str,
    *,
    vt_client: VirusTotalClient,
    quarantine_dir: Path,
    logs_dir: Path | None = None,
    source: str = "manual",
    max_file_size_mb: int = 25,
    max_uncompressed_mb: int = 200,
    max_pdf_pages: int = 500,
    unknown_policy: str = "parse_flagged",
) -> FileReport:
    extension = Path(filename).suffix.lower()
    warnings: list[str] = []

    size_mb = len(content) / 1_048_576
    if size_mb > max_file_size_mb:
        raise ValueError(f"archivo de {size_mb:.1f} MB excede el límite de {max_file_size_mb} MB")

    sha256 = sha256_bytes(content)
    md5 = md5_bytes(content)
    quarantine_path = store(content, sha256, quarantine_dir)

    verdict: VTVerdict = await vt_client.lookup_hash(sha256)

    detected = magic.from_buffer(content[:8192], mime=True)
    mime = registry.resolve_mime(detected, extension)
    mismatch = _extension_mismatches(mime, extension)
    if mismatch:
        warnings.append(f"El contenido real ({mime}) no corresponde a la extensión {extension}")

    decision, reason = _decide(verdict, mime, extension, mismatch, unknown_policy)

    report = FileReport(
        filename=filename,
        source=source,
        size_bytes=len(content),
        sha256=sha256,
        md5=md5,
        mime=mime,
        declared_extension=extension,
        extension_mismatch=mismatch,
        virustotal=verdict,
        decision=decision,
        reason=reason,
        quarantine_path=str(quarantine_path),
        warnings=warnings,
    )

    if decision is not Decision.ALLOW:
        log_event(
            "file.blocked" if decision is Decision.BLOCK else "file.held",
            f"{filename}: {reason}",
            level=Level.CRITICAL if decision is Decision.BLOCK else Level.WARN,
            logs_dir=logs_dir,
            sha256=sha256,
            source=source,
            vt_status=str(verdict.status),
            vt_detections=f"{verdict.malicious}/{verdict.total_engines}",
        )
        return report

    if verdict.status in (VTStatus.UNKNOWN, VTStatus.ERROR, VTStatus.SKIPPED):
        report.warnings.append("Contenido no verificado por VirusTotal")

    report.metadata, report.text, extraction_warnings = _parse(
        content, mime, max_uncompressed_mb, max_pdf_pages
    )
    report.warnings.extend(extraction_warnings)
    report.text_chars = len(report.text or "")

    log_event(
        "file.ingested",
        f"{filename}: {report.text_chars} caracteres extraídos ({mime})",
        level=Level.INFO,
        logs_dir=logs_dir,
        sha256=sha256,
        source=source,
        vt_status=str(verdict.status),
    )
    return report


def _extension_mismatches(mime: str, extension: str) -> bool:
    expected = {
        ".pdf": {registry.MIME_PDF},
        ".pptx": {registry.MIME_PPTX},
        ".xlsx": {registry.MIME_XLSX},
        ".csv": {registry.MIME_CSV, registry.MIME_TEXT},
        ".txt": {registry.MIME_TEXT},
        ".md": {registry.MIME_TEXT, "text/markdown"},
    }.get(extension)
    return bool(expected) and mime not in expected


def _decide(
    verdict: VTVerdict, mime: str, extension: str, mismatch: bool, unknown_policy: str
) -> tuple[Decision, str]:
    if verdict.status is VTStatus.MALICIOUS:
        return Decision.BLOCK, (
            f"VirusTotal: {verdict.malicious}/{verdict.total_engines} motores lo marcan "
            "como malicioso. Ningún parser lo abre."
        )
    if verdict.status is VTStatus.SUSPICIOUS:
        return Decision.BLOCK, (
            f"VirusTotal: {verdict.suspicious} motores lo marcan como sospechoso."
        )
    if registry.is_executable(mime, extension):
        return Decision.BLOCK, f"Ejecutable o script ({mime}): bloqueado sin importar el veredicto."
    if mismatch:
        return Decision.HOLD, (
            f"El archivo dice ser {extension} pero su contenido real es {mime}. "
            "Retenido para revisión manual."
        )
    if verdict.status in (VTStatus.UNKNOWN, VTStatus.ERROR, VTStatus.SKIPPED):
        if unknown_policy == "hold":
            return Decision.HOLD, f"No verificado ({verdict.detail}) y la política es 'hold'."
        return Decision.ALLOW, f"No verificado por VirusTotal ({verdict.status}); se marca la nota."
    return Decision.ALLOW, f"Limpio según {verdict.total_engines} motores de VirusTotal."


def _parse(
    content: bytes, mime: str, max_uncompressed_mb: int, max_pdf_pages: int
) -> tuple[dict, str | None, list[str]]:
    if mime not in registry.SUPPORTED:
        return {}, None, [f"Tipo {mime} sin extractor: se guarda solo el hash y los metadatos."]

    try:
        if mime in (registry.MIME_PPTX, registry.MIME_XLSX):
            registry.guard_zip_bomb(content, max_uncompressed_mb * 1_048_576)

        if mime == registry.MIME_PDF:
            text, warns = pdf_x.extract(content, max_pdf_pages)
            return pdf_x.metadata(content), text, warns
        if mime == registry.MIME_PPTX:
            text, warns = pptx_x.extract(content)
            return pptx_x.metadata(content), text, warns
        if mime == registry.MIME_XLSX:
            text, warns = xlsx_x.extract(content)
            return xlsx_x.metadata(content), text, warns
        if mime == registry.MIME_CSV:
            text, warns = csv_x.extract(content)
            return csv_x.metadata(content), text, warns
        text, warns = csv_x.extract_text(content)
        return csv_x.metadata(content), text, warns
    except Exception as exc:
        # Un parser que revienta no debe tumbar la ingesta: el hash y el veredicto ya son valiosos.
        return {}, None, [f"Extracción fallida: {type(exc).__name__}: {exc}"]
