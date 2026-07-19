"""Constantes vitales del agente: UN solo archivo TOON, `heartbeat/heart.beat`.

Antes era un .md por día con el parte en prosa. Servía para leerlo, no para
medir: para saber el ritmo de la última semana había que abrir siete archivos y
parsear texto.

Una fila POR LATIDO, no por día. El BPM real es la mediana del hueco entre
latidos consecutivos, así que necesita los instantes; con totales diarios se
pierde. Agrupar por día, semana o mes se hace luego sobre estas filas.

    agente: U2NyaWJl
    desde: "2026-07-14T23:38:50Z"
    beats[8760]{ts,trigger,correos,relevantes,archivos,bloqueados,personas,eventos,avisos,errores}:
      "2026-07-19T11:41:40Z",schedule,3,0,0,0,0,0,0,0
"""

from datetime import datetime, timezone

from app.integrations.github import GitHubClient
from app.vault import toon

PATH = "heartbeat/heart.beat"

# Un año de latidos horarios. Pasado eso se recorta por la cola: lo viejo ya está
# resumido en la bitácora y nadie mide el BPM de hace catorce meses.
MAX_BEATS = 9000

COLUMNS = ("ts", "trigger", "correos", "relevantes", "archivos", "bloqueados",
           "personas", "eventos", "avisos", "errores")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def beat_row(pulse) -> dict:
    """Un latido en números. Todas las filas llevan las mismas columnas: así la
    tabla no se ensancha con el tiempo y cada fila cuesta lo mismo."""
    i = pulse.intake
    return {
        "ts": pulse.at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "trigger": pulse.trigger,
        "correos": i.processed,
        "relevantes": i.relevant,
        "archivos": i.files_stored,
        "bloqueados": i.files_blocked,
        "personas": i.people_new,
        "eventos": len(i.events_created),
        "avisos": len(pulse.reminders_sent),
        "errores": len(pulse.errors),
    }


async def read(vault: GitHubClient) -> list[dict]:
    note = await vault.read_note(PATH)
    if not note:
        return []
    try:
        return toon.decode(note.content).get("beats", [])
    except ValueError:
        return []


async def record(vault: GitHubClient, pulse) -> str:
    """Añade el latido actual y devuelve la ruta escrita."""
    beats = await read(vault)
    beats.append(beat_row(pulse))
    beats.sort(key=lambda b: b.get("ts", ""), reverse=True)
    del beats[MAX_BEATS:]

    desde = beats[-1]["ts"] if beats else _now()
    await vault.write_note(
        PATH,
        toon.encode({"agente": "U2NyaWJl", "desde": desde,
                     "latidos": len(beats), "beats": beats}),
        f"vitals: latido {pulse.trigger}",
    )
    return PATH
