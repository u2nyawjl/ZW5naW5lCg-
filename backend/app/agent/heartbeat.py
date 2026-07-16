"""El latido: orquestador del agente.

Cada tick (cron cada 30 min, o wake por correo urgente, o disparo manual):
  1. Lee la misión y el estado actual de la bóveda.
  2. Ingesta de correo: clasifica lo nuevo con el LLM y guarda lo relevante.
  3. Recordatorios: avisa de lo que entra en ventana (día antes / inminente).
  4. Vuelca los eventos al timeline durable de la bóveda.
  5. Escribe un parte de estado corto (plantilla, sin gastar tokens).
  6. Avisa al dueño SOLO si hay algo que amerite.

Cada fase falla por su cuenta: que Calendar esté caído no debe dejar sin ingesta al correo.

    python -m app.agent.heartbeat
"""

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agent import reminders
from app.agent.brain import Brain
from app.agent.intake import IntakeResult, process_inbox
from app.comms.email import EmailClient
from app.config import get_settings
from app.core.events import Level, log_event
from app.integrations.firestore import FirestoreClient
from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient
from app.security.virustotal import VirusTotalClient
from app.vault import embed, manifest, people, timeline


@dataclass
class Pulse:
    trigger: str
    at: datetime
    tasks: list[dict] = field(default_factory=list)
    intake: IntakeResult = field(default_factory=IntakeResult)
    reminders_sent: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


async def _read_vault_text(vault: GitHubClient, path: str, fallback: str) -> str:
    try:
        note = await vault.read_note(path)
        return note.content if note else fallback
    except Exception:
        return fallback


async def beat() -> int:
    settings = get_settings()
    trigger = os.getenv("HEARTBEAT_TRIGGER", "manual")
    now = datetime.now(timezone.utc)
    pulse = Pulse(trigger=trigger, at=now)

    vault = GitHubClient(settings.vault_github_token, settings.vault_repo_owner,
                         settings.vault_repo_name, settings.vault_repo_branch)
    engine = GitHubClient(settings.issues_token, settings.agent_repo_owner,
                          settings.agent_repo_name)
    brain = Brain(settings.github_models_token, settings.github_models_base_url,
                  settings.github_models_model)
    google = GoogleClient(settings.google_oauth_client_id, settings.google_oauth_client_secret,
                          settings.google_oauth_refresh_token, settings.gdrive_root_folder_id,
                          settings.google_calendar_id)
    mail = EmailClient(settings.gmail_address, settings.imap_password, settings.imap_host,
                       settings.imap_port, settings.smtp_host, settings.smtp_port)
    smtp = EmailClient(settings.gmail_address, settings.smtp_password,
                       smtp_host=settings.smtp_host, smtp_port=settings.smtp_port)
    vt = VirusTotalClient(settings.virustotal_api_key)

    mission = await _read_vault_text(vault, "system/mission.md", "Secretario general.")
    state = await _read_vault_text(vault, "system/state.md", "")
    contexto = f"{mission}\n\n## Contexto actual\n{state}" if state else mission

    # 1. Tareas. Los issues de seguridad (sondeos al gateway) también viven en Issues,
    # pero no son tareas del dueño: se excluyen para no ensuciar su lista.
    try:
        todos = await engine.open_tasks()
        pulse.tasks = [
            t for t in todos
            if not any(lab["name"] in ("seguridad", "alerta") for lab in t.get("labels", []))
        ]
    except Exception as exc:
        pulse.errors.append(f"tareas: {type(exc).__name__}: {exc}")

    # 2. Ingesta de correo
    try:
        pulse.intake = await process_inbox(
            settings, brain=brain, vault=vault, google=google, mail=mail,
            vt_client=vt, mission=contexto,
        )
        pulse.events.extend(pulse.intake.events)
        pulse.errors.extend(pulse.intake.errors)
        print(f"✅ Ingesta  · {pulse.intake.processed} correos, "
              f"{pulse.intake.relevant} relevantes, {pulse.intake.files_stored} archivos, "
              f"{pulse.intake.people_new} personas nuevas, "
              f"{len(pulse.intake.events_created)} eventos")
    except Exception as exc:
        pulse.errors.append(f"ingesta: {type(exc).__name__}: {exc}")
        print(f"❌ Ingesta  · {exc}")

    # 3. Recordatorios
    try:
        pulse.reminders_sent, tl = await reminders.check(google, vault, smtp, settings.owner_email)
        pulse.events.extend(tl)
        if pulse.reminders_sent:
            print(f"✅ Avisos   · {len(pulse.reminders_sent)} recordatorio(s)")
    except Exception as exc:
        pulse.errors.append(f"recordatorios: {type(exc).__name__}: {exc}")

    # 3b. Índice semántico. Va después de la ingesta porque indexa las notas que ésta
    # acaba de escribir, y antes del timeline para que su evento quede en la bitácora.
    # Solo re-embebe lo que cambió: un latido sin correo nuevo no gasta una llamada.
    try:
        idx = await embed.build_index(vault, brain)
        if idx["indexed"]:
            pulse.events.append(timeline.event(
                "index",
                f"Índice semántico: {idx['indexed']} nota(s) re-embebida(s), "
                f"{idx['total']} indexadas en total",
            ))
            print(f"✅ Índice   · {idx['indexed']} re-embebidas, {idx['total']} totales")
        else:
            print(f"· Índice   · sin cambios ({idx['total']} notas)")
    except Exception as exc:
        pulse.errors.append(f"índice: {type(exc).__name__}: {exc}")
        print(f"❌ Índice   · {exc}")

    # 4. Timeline durable + resumen del latido
    pulse.events.append(timeline.event(
        "heartbeat", f"Latido ({trigger}): {pulse.intake.relevant} correos relevantes, "
        f"{len(pulse.reminders_sent)} avisos", level="warn" if pulse.errors else "info",
    ))
    try:
        await timeline.append(vault, pulse.events)
    except Exception as exc:
        pulse.errors.append(f"timeline: {exc}")

    # 4b. Espejo en Firestore para que el dashboard lea en vivo (sin polling).
    if settings.firebase_service_account_b64 and settings.firebase_project_id:
        try:
            await _mirror_to_firestore(settings, pulse, vault, brain)
            print("✅ Firestore· estado, tareas y timeline reflejados")
        except Exception as exc:
            pulse.errors.append(f"firestore: {type(exc).__name__}: {exc}")
            print(f"❌ Firestore· {exc}")

    # 5. Parte de estado en la bóveda
    try:
        await vault.write_note(
            f"heartbeat/{now:%Y-%m-%d}.md", _render_note(pulse),
            f"heartbeat: {now:%Y-%m-%d} ({trigger})",
        )
        print(f"✅ Bóveda   · heartbeat/{now:%Y-%m-%d}.md")
    except Exception as exc:
        pulse.errors.append(f"bóveda: {exc}")

    # 6. Aviso solo si hay algo
    if _is_noteworthy(pulse):
        subject, body = _render_report(pulse)
        try:
            await smtp.send(settings.owner_email, subject, body)
            print(f"✅ Correo   · aviso a {settings.owner_email}")
        except Exception as exc:
            pulse.errors.append(f"envío: {exc}")
    else:
        print("· Correo   · latido silencioso")

    log_event(
        "agent.heartbeat",
        f"Latido ({trigger}): {pulse.intake.relevant} relevantes, "
        f"{len(pulse.reminders_sent)} avisos, {len(pulse.errors)} fallos",
        level=Level.WARN if pulse.errors else Level.INFO, logs_dir=settings.logs_dir,
    )
    for err in pulse.errors:
        print(f"⚠️  {err}")

    for c in (brain, google, vault, engine, vt):
        await c.aclose()
    return 0


async def _mirror_to_firestore(settings, pulse: Pulse, vault: GitHubClient, brain: Brain) -> None:
    fs = FirestoreClient(settings.firebase_service_account_b64, settings.firebase_project_id)
    try:
        await fs.set("status/current", {
            "agent_core": "online",
            "honeypot": "armed" if settings.honeypot_enabled else "disabled",
            "trigger": pulse.trigger,
            "at": pulse.at.isoformat(timespec="seconds"),
            "relevant_emails": pulse.intake.relevant,
            "reminders": len(pulse.reminders_sent),
            "errors": len(pulse.errors),
        })
        # Tareas y archivos como documento único (cambian/desaparecen): estado completo.
        await fs.set("tasks/current", {
            "items": [{"number": t["number"], "title": t["title"]} for t in pulse.tasks],
            "at": pulse.at.isoformat(timespec="seconds"),
        })
        files = await manifest.load(vault)
        await fs.set("files/current", {"items": files[:100],
                                       "at": pulse.at.isoformat(timespec="seconds")})
        # Base de datos de personas.
        directory = await people.load(vault)
        await fs.set("people/current", {"items": people.as_list(directory)[:500],
                                        "at": pulse.at.isoformat(timespec="seconds")})
        # Uso de tokens del cerebro (acumulado; el chat suma aparte desde el gateway).
        if brain.usage["total_tokens"] > 0:
            cur = await fs.get("usage/current") or {}
            today = pulse.at.strftime("%Y-%m-%d")
            same_day = cur.get("today_date") == today
            await fs.set("usage/current", {
                "prompt_tokens": int(cur.get("prompt_tokens", 0)) + brain.usage["prompt_tokens"],
                "completion_tokens": int(cur.get("completion_tokens", 0)) + brain.usage["completion_tokens"],
                "total_tokens": int(cur.get("total_tokens", 0)) + brain.usage["total_tokens"],
                "calls": int(cur.get("calls", 0)) + brain.usage["calls"],
                "agent_tokens": int(cur.get("agent_tokens", 0)) + brain.usage["total_tokens"],
                "chat_tokens": int(cur.get("chat_tokens", 0)),
                "today_date": today,
                "today_tokens": (int(cur.get("today_tokens", 0)) if same_day else 0) + brain.usage["total_tokens"],
                "model": settings.github_models_model,
                "updated_at": pulse.at.isoformat(timespec="seconds"),
            })

        # Timeline: cada evento es un documento append-only.
        for ev in pulse.events:
            await fs.add("timeline", ev)
    finally:
        await fs.aclose()


def _is_noteworthy(pulse: Pulse) -> bool:
    return bool(pulse.tasks or pulse.intake.relevant or pulse.reminders_sent or pulse.errors)


def _render_report(pulse: Pulse) -> tuple[str, str]:
    """Parte corto y preciso. Plantilla, cero tokens de LLM."""
    partes = []
    if pulse.intake.relevant:
        partes.append(f"{pulse.intake.relevant} correos")
    if pulse.reminders_sent:
        partes.append(f"{len(pulse.reminders_sent)} recordatorios")
    if pulse.tasks:
        partes.append(f"{len(pulse.tasks)} tareas")
    if pulse.errors:
        partes.append("incidencias")
    subject = f"U2NyaWJl · {' · '.join(partes) if partes else 'sin novedades'}"

    body = [f"Estado · {pulse.at:%Y-%m-%d %H:%M} UTC ({pulse.trigger})", ""]
    body.append(f"Correo relevante: {pulse.intake.relevant}/{pulse.intake.processed}   "
                f"Archivos: {pulse.intake.files_stored}   Tareas: {len(pulse.tasks)}   "
                f"Personas nuevas: {pulse.intake.people_new}")
    if pulse.intake.events_created:
        body += ["", "Agendado en el calendario:"] + [f"  📅 {e}" for e in pulse.intake.events_created]
    if pulse.reminders_sent:
        body += ["", "Recordatorios:"] + [f"  ⏰ {r}" for r in pulse.reminders_sent]
    if pulse.intake.notes:
        body += ["", "Guardado en la bóveda:"] + [f"  · {n}" for n in pulse.intake.notes]
    if pulse.tasks:
        body += ["", "Tareas:"] + [f"  #{t['number']} · {t['title']}" for t in pulse.tasks]
    if pulse.errors:
        body += ["", "Fallos:"] + [f"  ⚠️ {e}" for e in pulse.errors]
    return subject, "\n".join(body)


def _render_note(pulse: Pulse) -> str:
    lines = [
        "---", "tipo: heartbeat", f"fecha: {pulse.at:%Y-%m-%d}",
        f"disparo: {pulse.trigger}", f"actualizado: {pulse.at.isoformat(timespec='seconds')}",
        "---", "", f"# Latido · {pulse.at:%Y-%m-%d}", "",
        f"Despertado por **{pulse.trigger}** a las {pulse.at:%H:%M} UTC.", "",
        "## Correo",
        f"- Procesados: {pulse.intake.processed}",
        f"- Relevantes: {pulse.intake.relevant}",
        f"- Archivos guardados: {pulse.intake.files_stored}"
        + (f" · bloqueados: {pulse.intake.files_blocked}" if pulse.intake.files_blocked else ""),
    ]
    if pulse.intake.notes:
        lines += ["", "## Guardado", ""] + [f"- [[{n}]]" for n in pulse.intake.notes]
    if pulse.reminders_sent:
        lines += ["", "## Recordatorios enviados", ""] + [f"- ⏰ {r}" for r in pulse.reminders_sent]
    lines += ["", "## Tareas abiertas", ""]
    lines += [f"- [ ] #{t['number']} {t['title']}" for t in pulse.tasks] or ["_Ninguna._"]
    if pulse.errors:
        lines += ["", "## Fallos", ""] + [f"- ⚠️ {e}" for e in pulse.errors]
    lines += ["", "---", "_Generado por U2NyaWJl._"]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(asyncio.run(beat()))
