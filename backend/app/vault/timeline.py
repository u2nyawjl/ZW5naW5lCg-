"""Bitácora durable en la bóveda: UN solo archivo TOON.

Antes era un .json por día. El problema no era el tamaño sino quién lo lee: para
saber qué pasó esta semana había que abrir siete archivos, y cada uno repetía el
nombre de cada campo en cada evento. Ahora es una tabla: las columnas se declaran
una vez y cada evento es una fila.

    generado: 2026-07-19T11:41:40Z
    eventos: 312
    events[312]{ts,type,level,message,sender,category}:
      "2026-07-19T11:41:40Z",heartbeat,info,"Latido: 0 relevantes",,

Se escribe un commit por latido (lote), no uno por evento.
"""

from datetime import datetime, timezone

from app.integrations.github import GitHubClient
from app.vault import toon

PATH = "timeline/timeline.dat"

# Cuántos eventos se conservan con detalle. A ~25 eventos/día son unos 8 meses.
# Sin tope, cada latido reescribiría un archivo que solo crece, y como la bóveda
# es git eso se paga para siempre en el historial.
MAX_EVENTS = 6000


def _now() -> str:
    # Z en vez de +00:00: dos caracteres menos en la columna más repetida y es
    # la forma que todo el mundo (y el Date de JS) entiende sin dudar.
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def read(vault: GitHubClient) -> list[dict]:
    """Los eventos guardados, del más reciente al más antiguo."""
    note = await vault.read_note(PATH)
    if not note:
        return []
    try:
        return toon.decode(note.content).get("events", [])
    except ValueError:
        # Un archivo corrupto no debe tumbar el latido: se avisa y se empieza de
        # cero, que es preferible a que el agente deje de funcionar por su diario.
        return []


async def append(vault: GitHubClient, events: list[dict]) -> None:
    if not events:
        return

    existing = await read(vault)
    existing.extend(events)
    # Más recientes primero: el dashboard pinta desde arriba y no tiene que ordenar.
    existing.sort(key=lambda e: e.get("ts", ""), reverse=True)
    del existing[MAX_EVENTS:]

    await vault.write_note(
        PATH,
        toon.encode({"generado": _now(), "eventos": len(existing), "events": existing}),
        f"timeline: +{len(events)} evento(s)",
    )


def event(type_: str, message: str, level: str = "info", **meta) -> dict:
    return {"ts": _now(), "type": type_, "level": level, "message": message, **meta}
