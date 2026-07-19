"""Bitácora y constantes vitales en archivo único TOON."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.agent.intake import IntakeResult
from app.vault import timeline, vitals


class FakeVault:
    """Bóveda en memoria: lo que importa aquí es qué se escribe, no cómo viaja."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.commits: list[str] = []

    async def read_note(self, path):
        if path not in self.store:
            return None
        return type("Note", (), {"content": self.store[path], "path": path})()

    async def write_note(self, path, content, message):
        self.store[path] = content
        self.commits.append(message)
        return True


@dataclass
class FakePulse:
    trigger: str = "schedule"
    at: datetime = field(default_factory=lambda: datetime(2026, 7, 19, 11, 41, tzinfo=timezone.utc))
    intake: IntakeResult = field(default_factory=IntakeResult)
    reminders_sent: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    events: list = field(default_factory=list)


# ── bitácora ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_solo_archivo_y_no_uno_por_dia():
    v = FakeVault()
    await timeline.append(v, [timeline.event("heartbeat", "primero")])
    await timeline.append(v, [timeline.event("index", "segundo")])
    assert list(v.store) == ["timeline/timeline.dat"]
    assert len(await timeline.read(v)) == 2


@pytest.mark.asyncio
async def test_los_eventos_sobreviven_la_ida_y_vuelta():
    v = FakeVault()
    ev = timeline.event("email.discarded", "Descartado (ruido): hola, qué tal",
                        sender="a@b.com", category="ruido")
    await timeline.append(v, [ev])
    assert (await timeline.read(v))[0] == ev


@pytest.mark.asyncio
async def test_mas_recientes_primero():
    v = FakeVault()
    await timeline.append(v, [
        {"ts": "2026-07-14T10:00:00Z", "type": "a", "level": "info", "message": "viejo"},
        {"ts": "2026-07-19T10:00:00Z", "type": "b", "level": "info", "message": "nuevo"},
    ])
    assert [e["message"] for e in await timeline.read(v)] == ["nuevo", "viejo"]


@pytest.mark.asyncio
async def test_se_recorta_por_la_cola(monkeypatch):
    """Sin tope, cada latido reescribe un archivo que solo crece, y la bóveda
    es git: eso se paga para siempre en el historial."""
    monkeypatch.setattr(timeline, "MAX_EVENTS", 3)
    v = FakeVault()
    await timeline.append(v, [
        {"ts": f"2026-07-{d:02d}T10:00:00Z", "type": "x", "level": "info", "message": str(d)}
        for d in range(10, 20)
    ])
    quedan = await timeline.read(v)
    assert [e["message"] for e in quedan] == ["19", "18", "17"]   # se van los viejos


@pytest.mark.asyncio
async def test_archivo_corrupto_no_tumba_el_latido():
    v = FakeVault()
    v.store[timeline.PATH] = "esto no es toon[[["
    assert await timeline.read(v) == []
    await timeline.append(v, [timeline.event("heartbeat", "sigue latiendo")])
    assert len(await timeline.read(v)) == 1


@pytest.mark.asyncio
async def test_sin_eventos_no_escribe_nada():
    v = FakeVault()
    await timeline.append(v, [])
    assert v.commits == []


def test_el_timestamp_termina_en_z():
    """Dos caracteres menos que +00:00 en la columna más repetida, y el Date de
    JS lo entiende sin ambigüedad."""
    assert timeline.event("x", "y")["ts"].endswith("Z")


# ── constantes vitales ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_una_fila_por_latido_no_por_dia():
    """El BPM es la mediana del hueco entre latidos: con totales diarios se pierde."""
    v = FakeVault()
    for h in (9, 10, 11):
        p = FakePulse(at=datetime(2026, 7, 19, h, 0, tzinfo=timezone.utc))
        await vitals.record(v, p)
    beats = await vitals.read(v)
    assert len(beats) == 3
    assert [b["ts"] for b in beats] == ["2026-07-19T11:00:00Z", "2026-07-19T10:00:00Z",
                                        "2026-07-19T09:00:00Z"]


@pytest.mark.asyncio
async def test_la_fila_lleva_los_numeros_del_latido():
    v = FakeVault()
    p = FakePulse(trigger="repository_dispatch")
    p.intake.processed, p.intake.relevant, p.intake.files_stored = 5, 2, 1
    p.intake.people_new = 3
    p.intake.events_created = ["Inducción"]
    p.reminders_sent = ["aviso"]
    p.errors = ["algo falló"]
    await vitals.record(v, p)
    fila = (await vitals.read(v))[0]
    assert fila == {"ts": "2026-07-19T11:41:00Z", "trigger": "repository_dispatch",
                    "correos": 5, "relevantes": 2, "archivos": 1, "bloqueados": 0,
                    "personas": 3, "eventos": 1, "avisos": 1, "errores": 1}


@pytest.mark.asyncio
async def test_todas_las_filas_tienen_las_mismas_columnas():
    """Si la tabla se ensanchara con el tiempo, cada fila vieja pagaría celdas
    vacías por columnas que solo usa una fila nueva."""
    v = FakeVault()
    await vitals.record(v, FakePulse())
    await vitals.record(v, FakePulse(at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)))
    cabecera = v.store[vitals.PATH].splitlines()
    header = next(l for l in cabecera if l.startswith("beats["))
    assert header == "beats[2]{" + ",".join(vitals.COLUMNS) + "}:"
