"""La cola de subidas.

El test que importa es el de la forma del retorno: `drain` tiene tres caminos de
salida y uno devolvía una tupla más corta, así que el latido reventaba justo
cuando no había nada en la cola — o sea, casi siempre.
"""

import pytest

from app.agent import uploads


class FakeVault:
    def __init__(self, store=None):
        self.store = store or {}

    async def read_note(self, path, fresh=False):
        if path not in self.store:
            return None
        return type("N", (), {"content": self.store[path], "path": path, "sha": "x"})()

    async def write_note(self, path, content, message):
        self.store[path] = content
        return True


class FakeStorage:
    def __init__(self, configured=True):
        self.configured = configured


@pytest.mark.asyncio
@pytest.mark.parametrize("caso,vault,storage", [
    ("sin bucket configurado", FakeVault(), FakeStorage(configured=False)),
    ("cola inexistente", FakeVault(), FakeStorage()),
    ("cola vacía", FakeVault({uploads.QUEUE_PATH: "[]"}), FakeStorage()),
])
async def test_drain_siempre_devuelve_cuatro_valores(caso, vault, storage):
    out = await uploads.drain(object(), vault=vault, google=None,
                              vt_client=None, storage=storage)
    assert len(out) == 4, f"{caso}: devolvió {len(out)} valores"
    hechos, esperando, errores, eventos = out
    assert (hechos, esperando, errores, eventos) == (0, 0, [], [])


@pytest.mark.asyncio
async def test_cola_ilegible_no_tumba_el_latido():
    v = FakeVault({uploads.QUEUE_PATH: "{no es json"})
    out = await uploads.drain(object(), vault=v, google=None,
                              vt_client=None, storage=FakeStorage())
    assert out == (0, 0, [], [])
