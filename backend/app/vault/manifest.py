"""El sistema de archivos del agente.

Un JSON en la bóveda que lista TODO lo que el agente ha guardado: nombre, hash,
veredicto de VirusTotal, enlace en Drive y dónde vive su texto extraído. Esto es
lo que el cerebro lee cuando necesita saber "qué archivos tengo".

El hash es la clave primaria: el mismo archivo, llegue por donde llegue, no se
duplica en la lista.
"""

import json

from app.integrations.github import GitHubClient

MANIFEST_PATH = "files/manifest.json"


async def load(vault: GitHubClient) -> list[dict]:
    note = await vault.read_note(MANIFEST_PATH)
    if not note:
        return []
    try:
        return json.loads(note.content)
    except json.JSONDecodeError:
        return []


async def add(vault: GitHubClient, entry: dict) -> list[dict]:
    """Añade o actualiza una entrada (identificada por sha256). Devuelve la lista completa."""
    entries = await load(vault)
    by_hash = {e.get("sha256"): e for e in entries}
    by_hash[entry["sha256"]] = {**by_hash.get(entry["sha256"], {}), **entry}

    merged = list(by_hash.values())
    merged.sort(key=lambda e: e.get("ingested_at", ""), reverse=True)

    await vault.write_note(
        MANIFEST_PATH,
        json.dumps(merged, ensure_ascii=False, indent=2),
        f"files: registra {entry.get('filename', entry['sha256'][:12])}",
    )
    return merged


def entry_from_report(report, drive_link: str, note_path: str) -> dict:
    """Traduce un FileReport del pipeline a una fila del manifiesto."""
    return {
        "filename": report.filename,
        "sha256": report.sha256,
        "mime": report.mime,
        "size_bytes": report.size_bytes,
        "source": report.source,
        "ingested_at": report.ingested_at.isoformat(),
        "vt_status": str(report.virustotal.status),
        "vt_detections": f"{report.virustotal.malicious}/{report.virustotal.total_engines}",
        "decision": str(report.decision),
        "drive_link": drive_link,       # vacío si no se subió (bloqueado o retenido)
        "note_path": note_path,          # la nota .md con su texto y metadatos
        "text_chars": report.text_chars,
    }
