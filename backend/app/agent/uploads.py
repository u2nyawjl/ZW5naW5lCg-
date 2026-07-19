"""La cola de archivos subidos a mano desde el dashboard.

El gateway no procesa nada: recibe el archivo, lo deja en Firebase Storage y
anota una entrada aquí. Quien tiene el pipeline entero —VirusTotal, Unstructured,
Drive, manifiesto— es el latido, así que procesa él.

Esa división es lo que hace que el reintento salga gratis: si VirusTotal está sin
cuota, la entrada simplemente no se borra de la cola y el siguiente latido vuelve
a intentarlo.

Ojo con qué se reintenta:
  ERROR    cuota agotada o red caída  → reintentar, mañana funciona
  UNKNOWN  VT no ha visto ese hash    → NO: es lo normal en un documento privado
           y reintentarlo lo dejaría dando vueltas para siempre sin entrar nunca
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.integrations.github import GitHubClient
from app.integrations.storage import StorageClient
from app.security.models import Decision, VTStatus
from app.security.pipeline import ingest_file
from app.vault import manifest, timeline

QUEUE_PATH = "files/queue.json"
PENDING_PREFIX = "pending/"

# Tras esto se deja de intentar y se avisa: si VT lleva un día entero sin
# responder, el problema no se arregla solo y hay que mirarlo.
MAX_ATTEMPTS = 24


def _slug(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen] or "archivo").strip("-")


async def load(vault: GitHubClient) -> list[dict]:
    note = await vault.read_note(QUEUE_PATH)
    if not note:
        return []
    try:
        data = json.loads(note.content)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def save(vault: GitHubClient, queue: list[dict], message: str) -> None:
    await vault.write_note(QUEUE_PATH, json.dumps(queue, ensure_ascii=False, indent=2), message)


def _render_note(report, item: dict, resumen: str = "") -> str:
    """El documento fusionado: qué es, qué dijo VirusTotal y qué sacó Unstructured.

    Todo en una nota para que el agente lo encuentre buscando y lo lea de una vez,
    en vez de tener que cruzar tres archivos.
    """
    vt = report.virustotal
    carpeta = item.get("folder", "")
    head = [
        "---", "tipo: documento", f"archivo: {report.filename}",
        f"sha256: {report.sha256}", f"mime: {report.mime}",
        # `origen` dice CÓMO llegó; `coleccion`, dónde vive. Si origen repitiera la
        # carpeta, al mover el archivo quedarían dos carpetas distintas en la misma
        # nota — y de ese dato depende que no mezcle semestres.
        "origen: subida manual",
        f"subido: {item.get('uploaded_at', '')}",
        f"veredicto: {report.decision}",
    ]
    if carpeta:
        # La carpeta es la que le dice al agente de qué semestre es el material.
        # Sin esto mezclaría un informe del año pasado con el capstone vigente.
        head.append(f"coleccion: {carpeta}")
    head += ["---", "", f"# {report.filename}", ""]

    body = [
        "## Análisis de seguridad", "",
        f"- **VirusTotal:** {vt.status} · {vt.malicious}/{vt.total_engines} motores lo marcan",
        f"- **Decisión:** {report.decision} — {report.reason}",
        f"- **Tamaño:** {report.size_bytes / 1024:.1f} KB",
    ]
    if vt.permalink:
        body.append(f"- **Informe:** {vt.permalink}")
    if report.warnings:
        body += ["", "### Avisos", ""] + [f"- ⚠️ {w}" for w in report.warnings]

    if resumen:
        body += ["", "## Resumen", "", resumen]

    body += ["", "## Contenido extraído", ""]
    if report.text:
        body.append(report.text)
    else:
        body.append("_Sin texto extraíble (o el archivo no se abrió por seguridad)._")
    return "\n".join(head + body)


async def drain(settings, *, vault: GitHubClient, google, vt_client, storage: StorageClient,
                brain=None):
    """Procesa lo que haya en cola.

    Devuelve SIEMPRE (procesados, en_espera, errores, eventos): las cuatro, por
    todos los caminos.
    """
    # Los tres retornos devuelven la MISMA forma: (hechos, esperando, errores,
    # eventos). Que el camino corto devolviera una tupla más corta reventaba el
    # latido justo cuando no había nada que hacer, que es casi siempre.
    if not storage.configured:
        return 0, 0, [], []

    queue = await load(vault)
    if not queue:
        return 0, 0, [], []

    done, waiting, errors, events = 0, 0, [], []
    rest: list[dict] = []
    docs_folder = None

    for item in queue:
        blob = PENDING_PREFIX + item["sha256"]
        try:
            content = await storage.get(blob)
        except Exception as exc:
            errors.append(f"storage {item.get('filename')}: {exc}")
            rest.append(item)
            continue

        if content is None:
            # Ya no está: otro latido lo procesó. No es un fallo.
            continue

        try:
            report = await ingest_file(
                content, item["filename"],
                vt_client=vt_client,
                quarantine_dir=Path(settings.quarantine_dir),
                logs_dir=settings.logs_dir,
                source="subida",
                max_file_size_mb=settings.max_file_size_mb,
                max_uncompressed_mb=settings.max_uncompressed_mb,
                max_pdf_pages=settings.max_pdf_pages,
                unknown_policy=settings.vt_unknown_policy,
                unstructured_url=settings.unstructured_api_url,
                unstructured_key=settings.unstructured_api_key,
            )
        except Exception as exc:
            errors.append(f"{item.get('filename')}: {exc}")
            item["attempts"] = item.get("attempts", 0) + 1
            item["last_error"] = str(exc)[:200]
            if item["attempts"] < MAX_ATTEMPTS:
                rest.append(item)
            continue

        # El único motivo por el que se espera: VirusTotal no pudo contestar.
        if report.virustotal.status is VTStatus.ERROR:
            item["attempts"] = item.get("attempts", 0) + 1
            item["last_error"] = report.virustotal.detail or "VirusTotal no responde"
            if item["attempts"] >= MAX_ATTEMPTS:
                errors.append(f"{item['filename']}: VirusTotal lleva "
                              f"{item['attempts']} intentos sin responder")
                events.append(timeline.event(
                    "file.giveup", f"Se deja de reintentar {item['filename']}: "
                    f"VirusTotal no responde", level="warn"))
                continue
            rest.append(item)
            waiting += 1
            continue

        drive_link, drive_id = "", ""
        if report.decision is Decision.ALLOW and report.text is not None:
            if docs_folder is None:
                docs_folder = await google.ensure_folder("documentos")
            uploaded = await google.upload(
                item["filename"], content, mime=report.mime, folder_id=docs_folder)
            drive_link, drive_id = uploaded.link, uploaded.id
            events.append(timeline.event(
                "file.scanned", f"Subida procesada: {item['filename']}",
                vt=str(report.virustotal.status), sha256=report.sha256[:12]))
        elif report.decision is Decision.BLOCK:
            events.append(timeline.event(
                "file.blocked", f"Subida bloqueada: {item['filename']} — {report.reason}",
                level="alert", vt=str(report.virustotal.status)))

        # El resumen lo escribe la IA sobre el texto ya extraído. Es lo que hace
        # que una plantilla de 12 páginas se pueda mirar de un vistazo, y la base
        # sobre la que luego se rellenará una nueva.
        resumen = ""
        if brain and report.text and report.decision is Decision.ALLOW:
            try:
                resumen = await brain.summarize(
                    report.text[:6000],
                    "Resume este documento en 3-5 puntos. Di qué ES (plantilla, informe, "
                    "rúbrica…) y qué secciones o campos pide rellenar.")
            except Exception as exc:
                errors.append(f"resumen de {item['filename']}: {exc}")

        folder = item.get("folder", "").strip("/")
        note_path = (f"documents/{folder}/" if folder else "documents/") \
            + f"{report.sha256[:12]}-{_slug(item['filename'])}.md"
        await vault.write_note(note_path, _render_note(report, item, resumen),
                               f"docs: {item['filename']} (subida)")
        await manifest.add(vault, {
            **manifest.entry_from_report(report, drive_link, drive_id, note_path),
            "collection": folder,
            "summary": resumen,
            "size_bytes": report.size_bytes,
        })
        await storage.delete(blob)
        done += 1

    if len(rest) != len(queue):
        await save(vault, rest, f"files: cola -{len(queue) - len(rest)} pendiente(s)")
    elif rest != queue:
        await save(vault, rest, "files: actualiza intentos de la cola")

    return done, waiting, errors, events
