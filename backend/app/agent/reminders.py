"""Recordatorios con auto-despertar.

Serverless no puede agendar un job para cada recordatorio. El patrón correcto: el
latido periódico (cada 30 min) revisa los eventos próximos del Calendar y avisa cuando
cae en una ventana. No depende de la puntualidad del cron —usa umbrales, no instantes—:
en cuanto faltan ≤24 h avisa "un día antes", y en cuanto faltan ≤2 h avisa "inminente".

Qué recordatorios ya se enviaron se guarda en la bóveda, para no repetir el aviso en
cada latido.
"""

import json
from datetime import datetime, timedelta, timezone

from app.comms.email import EmailClient
from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient
from app.vault import timeline

STATE_PATH = "reminders/notified.json"

DAY_BEFORE = timedelta(hours=24)
IMMINENT = timedelta(hours=2)


async def _load_state(vault: GitHubClient) -> dict:
    note = await vault.read_note(STATE_PATH)
    if not note:
        return {}
    try:
        return json.loads(note.content)
    except json.JSONDecodeError:
        return {}


def _parse_start(event: dict) -> datetime | None:
    start = event.get("start", {})
    raw = start.get("dateTime") or start.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:  # eventos de día completo vienen sin hora
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def check(
    google: GoogleClient,
    vault: GitHubClient,
    mail: EmailClient,
    owner_email: str,
) -> tuple[list[str], list[dict]]:
    """Avisa de lo que entra en ventana. Devuelve (resúmenes, eventos-de-timeline)."""
    now = datetime.now(timezone.utc)
    events = await google.upcoming_events(since=now, limit=25)
    state = await _load_state(vault)

    sent: list[str] = []
    tl: list[dict] = []
    dirty = False

    for ev in events:
        start = _parse_start(ev)
        if start is None or start <= now:
            continue

        ttl = start - now
        eid = ev.get("id", "")
        already = set(state.get(eid, []))

        window = None
        if ttl <= IMMINENT and "imminent" not in already:
            window = "imminent"
        elif ttl <= DAY_BEFORE and "day_before" not in already:
            window = "day_before"
        if window is None:
            continue

        titulo = ev.get("summary", "(sin título)")
        cuando = start.strftime("%Y-%m-%d %H:%M UTC")
        horas = int(ttl.total_seconds() // 3600)
        etiqueta = "en menos de 2 horas" if window == "imminent" else f"en ~{horas} h"

        cuerpo = (
            f"Recordatorio: «{titulo}» {etiqueta}.\n\n"
            f"  Cuándo: {cuando}\n"
            f"  Dónde:  {ev.get('location', '—')}\n"
        )
        try:
            await mail.send(owner_email, f"⏰ {titulo} · {etiqueta}", cuerpo)
            state.setdefault(eid, []).append(window)
            dirty = True
            sent.append(f"{titulo} ({etiqueta})")
            tl.append(timeline.event(
                "reminder.sent", f"Recordatorio: {titulo} — {etiqueta}", when=cuando,
            ))
        except Exception as exc:
            tl.append(timeline.event(
                "reminder.error", f"No se pudo avisar de {titulo}: {exc}", level="warn",
            ))

    if dirty:
        _prune(state, events)
        await vault.write_note(
            STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2),
            "reminders: actualiza avisos enviados",
        )

    return sent, tl


def _prune(state: dict, events: list[dict]) -> None:
    """Quita del estado los eventos que ya no aparecen (pasados): que no crezca sin fin."""
    vivos = {ev.get("id", "") for ev in events}
    for eid in list(state):
        if eid not in vivos:
            del state[eid]
