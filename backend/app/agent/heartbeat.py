"""El latido.

Se despierta por dos vías y no distingue mucho entre ellas:
  · cron  → una vez al día (12:00 UTC = 08:00 Santiago)
  · wake  → repository_dispatch, cuando entra un correo etiquetado `agent-wake`

Recoge el estado (tareas abiertas, eventos próximos, correo sin leer), lo deja escrito
en la bóveda y reporta al dueño. Es idempotente: la nota del día se sobrescribe, así que
dos latidos seguidos no duplican nada.

    python -m app.agent.heartbeat
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.comms.email import EmailClient
from app.config import get_settings
from app.core.events import Level, log_event
from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient


@dataclass
class Pulse:
    trigger: str
    at: datetime
    tasks: list[dict]
    events: list[dict]
    unread: int
    errors: list[str]


async def gather(settings, trigger: str) -> Pulse:
    now = datetime.now(timezone.utc)
    errors: list[str] = []
    tasks: list[dict] = []
    events: list[dict] = []
    unread = 0

    engine = GitHubClient(
        token=settings.issues_token,
        owner=settings.agent_repo_owner,
        repo=settings.agent_repo_name,
    )
    google = GoogleClient(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        refresh_token=settings.google_oauth_refresh_token,
        root_folder_id=settings.gdrive_root_folder_id,
        calendar_id=settings.google_calendar_id,
    )
    mail = EmailClient(
        address=settings.gmail_address,
        password=settings.imap_password,
        imap_host=settings.imap_host,
        imap_port=settings.imap_port,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
    )

    # Cada fuente falla por su cuenta: que Calendar esté caído no debe dejar
    # al agente sin reportar las tareas.
    try:
        tasks = await engine.open_tasks()
    except Exception as exc:
        errors.append(f"tareas: {type(exc).__name__}: {exc}")

    try:
        events = await google.upcoming_events(since=now, limit=10)
    except Exception as exc:
        errors.append(f"calendario: {type(exc).__name__}: {exc}")

    try:
        unread = len(await mail.fetch(label=settings.gmail_wake_label, unread_only=True))
    except Exception as exc:
        errors.append(f"correo: {type(exc).__name__}: {exc}")

    await engine.aclose()
    await google.aclose()

    return Pulse(trigger=trigger, at=now, tasks=tasks, events=events, unread=unread, errors=errors)


def render_note(pulse: Pulse, agent: str) -> str:
    fecha = pulse.at.strftime("%Y-%m-%d")
    lines = [
        "---",
        "tipo: heartbeat",
        f"fecha: {fecha}",
        f"disparo: {pulse.trigger}",
        f"actualizado: {pulse.at.isoformat(timespec='seconds')}",
        "---",
        "",
        f"# Latido · {fecha}",
        "",
        f"Despertado por **{pulse.trigger}** a las {pulse.at.strftime('%H:%M')} UTC.",
        "",
        "## Tareas abiertas",
        "",
    ]
    if pulse.tasks:
        lines += [f"- [ ] #{t['number']} {t['title']}" for t in pulse.tasks]
    else:
        lines.append("_Ninguna._")

    lines += ["", "## Próximos eventos", ""]
    if pulse.events:
        for e in pulse.events:
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "?")
            lines.append(f"- {start[:16]} · {e.get('summary', 'sin título')}")
    else:
        lines.append("_Ninguno._")

    lines += ["", "## Correo pendiente", "", f"{pulse.unread} sin leer con la etiqueta de despertar."]

    if pulse.errors:
        lines += ["", "## Fallos", ""] + [f"- ⚠️ {e}" for e in pulse.errors]

    lines += ["", "---", f"_Generado por {agent}._", ""]
    return "\n".join(lines)


def render_email(pulse: Pulse) -> tuple[str, str]:
    fecha = pulse.at.strftime("%Y-%m-%d %H:%M UTC")
    estado = "con incidencias" if pulse.errors else "sin incidencias"
    subject = f"U2NyaWJl · latido {pulse.at.strftime('%Y-%m-%d')} ({estado})"

    body = [
        "Hola mundo.",
        "",
        f"Soy U2NyaWJl. Este es mi primer latido: {fecha}, disparado por '{pulse.trigger}'.",
        "",
        f"  Tareas abiertas ....... {len(pulse.tasks)}",
        f"  Eventos próximos ...... {len(pulse.events)}",
        f"  Correo por revisar .... {pulse.unread}",
        "",
    ]
    if pulse.tasks:
        body += ["Tareas:"] + [f"  #{t['number']} · {t['title']}" for t in pulse.tasks] + [""]
    if pulse.events:
        body += ["Agenda:"]
        for e in pulse.events:
            start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date", "?")
            body.append(f"  {start[:16]} · {e.get('summary', 'sin título')}")
        body.append("")
    if pulse.errors:
        body += ["Fallos:"] + [f"  ⚠️ {e}" for e in pulse.errors] + [""]

    body += ["Vuelvo a dormir.", "", "--", "U2NyaWJl"]
    return subject, "\n".join(body)


async def beat() -> int:
    settings = get_settings()
    trigger = os.getenv("HEARTBEAT_TRIGGER", "manual")

    pulse = await gather(settings, trigger)

    vault = GitHubClient(
        token=settings.vault_github_token,
        owner=settings.vault_repo_owner,
        repo=settings.vault_repo_name,
        branch=settings.vault_repo_branch,
    )
    mail = EmailClient(
        address=settings.gmail_address,
        password=settings.smtp_password,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
    )

    fecha = pulse.at.strftime("%Y-%m-%d")
    try:
        await vault.write_note(
            f"heartbeat/{fecha}.md",
            render_note(pulse, settings.agent_name),
            f"heartbeat: latido {fecha} ({trigger})",
        )
        print(f"✅ Bóveda   · heartbeat/{fecha}.md")
    except httpx.HTTPStatusError as exc:
        pulse.errors.append(f"bóveda: HTTP {exc.response.status_code}")
        print(f"❌ Bóveda   · HTTP {exc.response.status_code}")
    finally:
        await vault.aclose()

    subject, body = render_email(pulse)
    try:
        await mail.send(settings.owner_email, subject, body)
        print(f"✅ Correo   · enviado a {settings.owner_email}")
    except Exception as exc:
        print(f"❌ Correo   · {type(exc).__name__}: {exc}")
        pulse.errors.append(f"envío: {exc}")

    log_event(
        "agent.heartbeat",
        f"Latido ({trigger}): {len(pulse.tasks)} tareas, {len(pulse.events)} eventos, "
        f"{pulse.unread} correos",
        level=Level.WARN if pulse.errors else Level.INFO,
        logs_dir=settings.logs_dir,
        trigger=trigger,
        errors=pulse.errors,
    )

    for err in pulse.errors:
        print(f"⚠️  {err}")

    # Un fallo en una fuente no tumba el latido: se reporta y se sigue.
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(beat()))
