"""Timeline durable en la bóveda.

Los eventos van a /tmp en el runner y se pierden al terminar. Este módulo los persiste
en la bóveda, un archivo por día, para que el dashboard tenga una consola de eventos real.

Se escribe UN commit por latido (lote), no uno por evento: cientos de commits al día
ensuciarían el historial de la bóveda para nada.
"""

import json
from datetime import datetime, timezone

from app.integrations.github import GitHubClient


def _path(day: datetime) -> str:
    return f"timeline/{day:%Y-%m-%d}.json"


async def append(vault: GitHubClient, events: list[dict]) -> None:
    if not events:
        return

    day = datetime.now(timezone.utc)
    path = _path(day)

    note = await vault.read_note(path)
    existing = []
    if note:
        try:
            existing = json.loads(note.content)
        except json.JSONDecodeError:
            existing = []

    existing.extend(events)
    # Se conservan los más recientes primero para que el dashboard no tenga que ordenar.
    existing.sort(key=lambda e: e.get("ts", ""), reverse=True)

    await vault.write_note(
        path,
        json.dumps(existing, ensure_ascii=False, indent=2),
        f"timeline: +{len(events)} evento(s)",
    )


def event(type_: str, message: str, level: str = "info", **meta) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": type_,
        "level": level,
        "message": message,
        **meta,
    }
