"""Índice semántico de la bóveda.

`grep` es literal: buscar "reunión de inicio" no encuentra una nota titulada
"Inducción Capstone". Este índice permite buscarla por significado, y es lo que
convierte el shell del chat en algo útil en vez de un buscador de subcadenas.

Se reconstruye en cada latido pero solo re-embebe lo que cambió: la clave es el
sha del blob de git, que cambia si y solo si cambia el contenido. Un latido sin
correo nuevo cuesta cero llamadas al modelo.

Los vectores se guardan normalizados (‖v‖=1) para que el coseno sea un simple
producto punto, y como float32 en base64: 256 dims ocupan ~1 KB por nota frente
a los ~30 KB de la misma lista en JSON. Así el índice completo cabe en memoria
del gateway y se busca sin numpy ni base de datos vectorial.
"""

import base64
import json
import math
from array import array
from datetime import datetime, timezone

from ..agent.brain import EMBED_MODEL

INDEX_PATH = "system/embeddings.json"
EMBED_DIM = 256

# Sube esto al cambiar la forma de una entrada: obliga a reconstruir en vez de
# servir un índice viejo al que le faltan campos.
INDEX_VERSION = 3

# Solo prosa. Los .json (personas, bitácora, manifiesto) son datos estructurados:
# meter 55 personas en un único vector no dice nada. Para eso el modelo hace `cat`.
# /memory entra aquí porque un recuerdo que no se puede encontrar no es un recuerdo.
# El núcleo va aparte: ese se inyecta siempre, no hace falta buscarlo.
INDEXABLE = ("inbox/", "documents/", "notes/", "system/", "memory/")

# El modelo corta cerca de 8k tokens; una nota más larga se trunca al indexar.
MAX_CHARS = 8000

# Cuántas notas por llamada. La API acepta lotes; agruparlas evita 60 round-trips.
BATCH = 32


def pack(vec: list[float]) -> str:
    """Normaliza y empaqueta a float32+base64."""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return base64.b64encode(array("f", [x / norm for x in vec]).tobytes()).decode()


def unpack(blob: str) -> array:
    """Desempaqueta un vector del índice. (El gateway tiene su propia copia de
    esto: es otro deploy y no puede importar el backend.)"""
    out = array("f")
    out.frombytes(base64.b64decode(blob))
    return out


def _prep(path: str, body: str) -> str:
    # El nombre del archivo lleva el asunto del correo: es parte de lo que se busca.
    title = path.rsplit("/", 1)[-1].removesuffix(".md")
    return f"{title}\n\n{body}"[:MAX_CHARS]


def _head(body: str, limit: int = 160) -> str:
    """Primeras líneas con texto, para que `search` muestre de qué va cada
    resultado sin tener que abrir la nota."""
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("---", "|", "```")):
            return line[:limit]
    return ""


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def build_index(vault, brain) -> dict:
    """Deja system/embeddings.json al día. Devuelve un resumen para la bitácora."""
    tree = await vault.tree()
    want = {
        e["path"]: e["sha"]
        for e in tree
        if e["type"] == "blob"
        and e["path"].endswith(".md")
        and e["path"].startswith(INDEXABLE)
    }

    old: dict = {}
    existing = await vault.read_note(INDEX_PATH)
    if existing:
        try:
            old = json.loads(existing.content)
        except ValueError:
            old = {}

    # Si cambia el modelo, las dimensiones o el esquema, lo viejo no sirve.
    stale = (old.get("model") != EMBED_MODEL
             or old.get("dim") != EMBED_DIM
             or old.get("v") != INDEX_VERSION)
    prev: dict = {} if stale else (old.get("notes") or {})

    # Lo que sigue vigente: misma ruta y mismo sha. Lo borrado desaparece solo,
    # porque `want` es la verdad y esto filtra contra ella.
    keep = {p: v for p, v in prev.items() if p in want and v.get("sha") == want[p]}
    todo = [p for p in want if p not in keep]

    if not todo and len(keep) == len(prev):
        return {"indexed": 0, "reused": len(keep), "total": len(keep), "wrote": False}

    notes = dict(keep)
    for batch in _batches(todo, BATCH):
        texts, heads = [], []
        for path in batch:
            note = await vault.read_note(path)
            body = note.content if note else ""
            texts.append(_prep(path, body))
            heads.append(_head(body))
        vectors = await brain.embed(texts, dimensions=EMBED_DIM)
        for path, text, head, vec in zip(batch, texts, heads, vectors):
            notes[path] = {"sha": want[path], "vec": pack(vec),
                           "chars": len(text), "head": head}

    payload = {
        "v": INDEX_VERSION,
        "model": EMBED_MODEL,
        "dim": EMBED_DIM,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes,
    }
    await vault.write_note(
        INDEX_PATH,
        json.dumps(payload, ensure_ascii=False),
        f"index: {len(todo)} nota(s) re-embebida(s), {len(notes)} en total",
    )
    return {"indexed": len(todo), "reused": len(keep), "total": len(notes), "wrote": True}
