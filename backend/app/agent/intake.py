"""Ingesta de correo: el núcleo de entrada del agente.

Por cada correo sin leer:
  1. El LLM decide si es relevante para la misión (mission.md).
  2. Si es ruido: se registra y se descarta.
  3. Si es relevante:
     - cada adjunto pasa por el pipeline (cuarentena → SHA-256 → VirusTotal → extracción),
     - los limpios suben a Drive; los peligrosos NO (solo queda su registro forense),
     - se anota en el manifiesto (el "sistema de archivos" del agente),
     - se escribe una nota de la bóveda con el resumen y los enlaces.

El correo se trata como dato no confiable de principio a fin: el LLM tiene prohibido
obedecer instrucciones que vengan dentro de un mensaje.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.agent.brain import Brain
from app.comms.email import EmailClient, Message
from app.core.events import Level, log_event
from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient
from app.security.models import Decision
from app.security.pipeline import ingest_file
from app.security.virustotal import VirusTotalClient
from app.vault import manifest, timeline


@dataclass
class IntakeResult:
    processed: int = 0
    relevant: int = 0
    files_stored: int = 0
    files_blocked: int = 0
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # para el timeline durable


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen] or "sin-asunto").strip("-")


async def process_inbox(
    settings,
    *,
    brain: Brain,
    vault: GitHubClient,
    google: GoogleClient,
    mail: EmailClient,
    vt_client: VirusTotalClient,
    mission: str,
) -> IntakeResult:
    result = IntakeResult()
    messages = await mail.fetch(label="", unread_only=True)

    for msg in messages:
        result.processed += 1
        try:
            await _process_one(msg, settings, brain, vault, google, vt_client, mission, result)
        except Exception as exc:
            result.errors.append(f"{msg.subject[:40]}: {type(exc).__name__}: {exc}")
            log_event(
                "intake.error", f"Fallo procesando '{msg.subject[:60]}': {exc}",
                level=Level.WARN, logs_dir=settings.logs_dir,
            )
        finally:
            # Marcar leído aunque falle: un correo que rompe el pipeline no debe
            # reprocesarse en bucle en cada latido. El fallo queda en el log.
            await mail.mark_seen(msg.uid)

    return result


async def _process_one(
    msg: Message, settings, brain, vault, google, vt_client, mission, result: IntakeResult
) -> None:
    verdict = await brain.classify_email(msg.sender, msg.subject, msg.body, mission)

    if not verdict["relevant"]:
        log_event(
            "intake.discarded", f"Ruido de {msg.sender}: {msg.subject[:60]}",
            level=Level.INFO, logs_dir=settings.logs_dir, category=verdict["category"],
        )
        result.events.append(timeline.event(
            "email.discarded", f"Descartado (ruido): {msg.subject[:60]}",
            sender=msg.sender, category=verdict["category"],
        ))
        return

    result.relevant += 1
    now = datetime.now(timezone.utc)
    stored_files: list[dict] = []

    docs_folder = await google.ensure_folder("documentos")

    for att in msg.attachments:
        report = await ingest_file(
            att.content, att.filename,
            vt_client=vt_client,
            quarantine_dir=Path(settings.quarantine_dir),
            logs_dir=settings.logs_dir,
            source="email",
            max_file_size_mb=settings.max_file_size_mb,
            max_uncompressed_mb=settings.max_uncompressed_mb,
            max_pdf_pages=settings.max_pdf_pages,
            unknown_policy=settings.vt_unknown_policy,
        )

        drive_link = ""
        note_path = f"documents/{report.sha256[:12]}-{_slug(att.filename)}.md"

        # Un archivo peligroso NO sube a Drive: subir malware a Google puede marcar
        # la cuenta. Queda su registro forense (hash + veredicto), no el binario.
        if report.decision is Decision.ALLOW and report.text is not None:
            uploaded = await google.upload(
                att.filename, att.content, mime=report.mime, folder_id=docs_folder
            )
            drive_link = uploaded.link
            result.files_stored += 1
            result.events.append(timeline.event(
                "file.scanned", f"Archivo guardado: {att.filename}",
                vt=str(report.virustotal.status), sha256=report.sha256[:12],
            ))
        elif report.decision is Decision.BLOCK:
            result.files_blocked += 1
            result.events.append(timeline.event(
                "file.blocked", f"Archivo bloqueado: {att.filename} — {report.reason}",
                level="alert", vt=str(report.virustotal.status),
            ))

        await vault.write_note(
            note_path, _render_file_note(report, msg, drive_link),
            f"docs: {att.filename} ({report.decision})",
        )
        entry = manifest.entry_from_report(report, drive_link, note_path)
        await manifest.add(vault, entry)
        stored_files.append(entry)

    inbox_note = f"inbox/{now:%Y-%m-%d}-{_slug(msg.subject)}.md"
    await vault.write_note(
        inbox_note, _render_inbox_note(msg, verdict, stored_files, now),
        f"inbox: {msg.subject[:50]}",
    )
    result.notes.append(inbox_note)

    log_event(
        "intake.saved",
        f"Guardado '{msg.subject[:50]}' de {msg.sender}: "
        f"{len(stored_files)} archivo(s), categoría {verdict['category']}",
        level=Level.INFO, logs_dir=settings.logs_dir,
    )
    result.events.append(timeline.event(
        "email.saved", f"Correo guardado ({verdict['category']}): {msg.subject[:60]}",
        sender=msg.sender, files=len(stored_files),
    ))


def _render_inbox_note(msg: Message, verdict: dict, files: list[dict], now: datetime) -> str:
    lines = [
        "---", "tipo: correo", f"remitente: {msg.sender}",
        f"categoria: {verdict['category']}", f"recibido: {now.isoformat(timespec='seconds')}",
        "---", "", f"# {msg.subject}", "",
        f"**De:** {msg.sender}  ", f"**Categoría:** {verdict['category']}  ",
        f"**Por qué importa:** {verdict['reason']}", "",
        "## Resumen", "", verdict["summary"] or "_(sin resumen)_",
    ]
    if files:
        lines += ["", "## Archivos adjuntos", ""]
        for f in files:
            estado = "✅" if f["drive_link"] else "⛔"
            link = f" · [Drive]({f['drive_link']})" if f["drive_link"] else ""
            lines.append(f"- {estado} `{f['filename']}` · VT: {f['vt_status']} "
                         f"({f['vt_detections']}) · [[{f['note_path']}]]{link}")
    lines += ["", "---", f"_Ingerido por U2NyaWJl · {now:%Y-%m-%d %H:%M} UTC._"]
    return "\n".join(lines)


def _render_file_note(report, msg: Message, drive_link: str) -> str:
    meta = "\n".join(f"- **{k}:** {v}" for k, v in report.metadata.items() if v)
    cuerpo = (report.text or "").strip()
    if len(cuerpo) > 6000:
        cuerpo = cuerpo[:6000] + "\n\n_(texto truncado)_"

    lines = [
        "---", "tipo: documento", f"archivo: {report.filename}",
        f"sha256: {report.sha256}", f"origen: {msg.sender}",
        f"decision: {report.decision}", "---", "",
        f"# {report.filename}", "",
        f"- **SHA-256:** `{report.sha256}`",
        f"- **Tipo real:** {report.mime}",
        f"- **VirusTotal:** {report.virustotal.status} "
        f"({report.virustotal.malicious}/{report.virustotal.total_engines})",
        f"- **Decisión:** {report.decision} — {report.reason}",
    ]
    if drive_link:
        lines.append(f"- **Drive:** {drive_link}")
    if meta:
        lines += ["", "## Metadatos", "", meta]
    if report.warnings:
        lines += ["", "## Avisos", ""] + [f"- ⚠️ {w}" for w in report.warnings]
    if cuerpo:
        lines += ["", "## Texto extraído", "", cuerpo]
    else:
        lines += ["", "_Sin texto extraído (bloqueado, retenido o sin capa de texto)._"]
    return "\n".join(lines)
