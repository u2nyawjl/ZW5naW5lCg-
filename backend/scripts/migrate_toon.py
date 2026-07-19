"""Migra la bóveda a archivo único TOON: timeline/*.json → timeline.dat,
heartbeat/*.md → heart.beat.

Los latidos históricos NO están en los .md (eran prosa). Se reconstruyen de la
propia bitácora, que sí guarda un evento `heartbeat` con su instante por cada
latido: así el BPM no arranca de cero.

    python -m scripts.migrate_toon --dry-run
    python -m scripts.migrate_toon
"""

import argparse
import asyncio
import json
import re
import sys

from app.config import get_settings
from app.integrations.github import GitHubClient
from app.vault import timeline, toon, vitals

# «Latido (schedule): 3 correos relevantes, 0 avisos»
_RESUMEN = re.compile(r"Latido \((?P<trigger>[^)]+)\):\s*(?P<rel>\d+)\s+correos?\s+relevantes?,"
                      r"\s*(?P<avisos>\d+)\s+avisos?")


async def main(dry: bool) -> int:
    s = get_settings()
    vault = GitHubClient(s.vault_github_token, s.vault_repo_owner,
                         s.vault_repo_name, s.vault_repo_branch)

    tree = await vault.tree()
    viejos_tl = sorted(e["path"] for e in tree
                       if re.fullmatch(r"timeline/\d{4}-\d{2}-\d{2}\.json", e["path"]))
    viejos_hb = sorted(e["path"] for e in tree
                       if re.fullmatch(r"heartbeat/\d{4}-\d{2}-\d{2}\.md", e["path"]))
    print(f"  {len(viejos_tl)} timeline/*.json  ·  {len(viejos_hb)} heartbeat/*.md")

    eventos: list[dict] = []
    for path in viejos_tl:
        note = await vault.read_note(path)
        if not note:
            continue
        try:
            eventos.extend(json.loads(note.content))
        except json.JSONDecodeError:
            print(f"  ⚠️  {path} ilegible, se salta")

    # Un mismo evento pudo quedar en dos archivos si un latido cruzó la medianoche.
    unicos = {(e.get("ts"), e.get("type"), e.get("message")): e for e in eventos}
    eventos = sorted(unicos.values(), key=lambda e: e.get("ts", ""), reverse=True)
    for e in eventos:
        if isinstance(e.get("ts"), str):
            e["ts"] = e["ts"].replace("+00:00", "Z")

    beats = []
    for e in eventos:
        if e.get("type") != "heartbeat":
            continue
        m = _RESUMEN.search(str(e.get("message", "")))
        beats.append({
            "ts": e["ts"],
            "trigger": m["trigger"] if m else "desconocido",
            "correos": 0,
            "relevantes": int(m["rel"]) if m else 0,
            "archivos": 0, "bloqueados": 0, "personas": 0, "eventos": 0,
            "avisos": int(m["avisos"]) if m else 0,
            "errores": 1 if e.get("level") == "warn" else 0,
        })

    print(f"  → {len(eventos)} eventos y {len(beats)} latidos reconstruidos")
    tl_txt = toon.encode({"generado": timeline._now(), "eventos": len(eventos),
                          "events": eventos})
    hb_txt = toon.encode({"agente": "U2NyaWJl", "desde": beats[-1]["ts"] if beats else "",
                          "latidos": len(beats), "beats": beats})
    print(f"  → {timeline.PATH}: {len(tl_txt)} bytes")
    print(f"  → {vitals.PATH}: {len(hb_txt)} bytes")

    # Releer lo generado antes de borrar nada: si el códec falla, mejor saberlo
    # ahora que después de haber borrado los originales.
    assert toon.decode(tl_txt)["events"] == eventos, "la bitácora no sobrevive la ida y vuelta"
    assert toon.decode(hb_txt)["beats"] == beats, "los latidos no sobreviven la ida y vuelta"
    print("  ✅ ida y vuelta verificada")

    if dry:
        print("\n  (simulacro: no se escribió ni se borró nada)")
        return 0

    await vault.write_note(timeline.PATH, tl_txt, "timeline: migra a archivo único TOON")
    await vault.write_note(vitals.PATH, hb_txt, "vitals: heart.beat desde la bitácora")
    print("  escritos los dos archivos nuevos")

    for path in viejos_tl + viejos_hb:
        await vault.delete_note(path, f"migración TOON: retira {path}")
        print(f"  borrado {path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args().dry_run)))
