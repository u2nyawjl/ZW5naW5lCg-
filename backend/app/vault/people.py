"""Directorio de personas en la bóveda: la "base de datos de personas" del agente.

Una sola fuente de verdad en `people/directory.json`, indexada por correo. Cada persona
guarda nombre, rol, primer/último visto y de qué correos salió. El heartbeat lo espeja a
Firestore (`people/current`) para que el dashboard lo lea en vivo.
"""

import json
from datetime import datetime, timezone

from app.integrations.github import GitHubClient

DIRECTORY = "people/directory.json"


async def load(vault: GitHubClient) -> dict:
    """Devuelve el directorio {correo: persona}. {} si aún no existe."""
    note = await vault.read_note(DIRECTORY)
    if not note:
        return {}
    try:
        data = json.loads(note.content)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def as_list(directory: dict) -> list[dict]:
    """El directorio como lista ordenada por nombre (para el dashboard)."""
    return sorted(directory.values(), key=lambda p: (p.get("name") or p.get("email", "")).lower())


async def merge(vault: GitHubClient, people: list[dict], source: str = "") -> tuple[int, int, list]:
    """Funde personas nuevas/actualizadas en el directorio. Devuelve (nuevas, actualizadas, lista)."""
    if not people:
        directory = await load(vault)
        return 0, 0, as_list(directory)

    directory = await load(vault)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new = updated = 0

    for p in people:
        key = p["email"]
        entry = directory.get(key)
        if entry is None:
            directory[key] = {
                "email": key, "name": p["name"], "role": p["role"],
                "first_seen": now, "last_seen": now,
                "sources": [source] if source else [],
            }
            new += 1
            continue

        changed = False
        # Un nombre "real" (con apellido) gana a uno derivado del correo.
        if " " in p["name"] and " " not in entry.get("name", ""):
            entry["name"] = p["name"]; changed = True
        # Un rol más específico gana a "externo".
        if p["role"] != "externo" and entry.get("role", "externo") == "externo":
            entry["role"] = p["role"]; changed = True
        if source and source not in entry.setdefault("sources", []):
            entry["sources"].append(source); changed = True
        entry["last_seen"] = now
        if changed:
            updated += 1

    if new or updated:
        await vault.write_note(
            DIRECTORY,
            json.dumps(directory, ensure_ascii=False, indent=2, sort_keys=True),
            f"people: +{new} nuevas, {updated} actualizadas",
        )

    return new, updated, as_list(directory)
