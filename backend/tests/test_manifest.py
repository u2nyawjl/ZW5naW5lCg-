import json

import httpx
import pytest
import respx

from app.integrations.github import GitHubClient
from app.vault import manifest

pytestmark = pytest.mark.asyncio

BASE = "https://api.github.com/repos/U2NyaWJl/vault/contents/files/manifest.json"


def _vault() -> GitHubClient:
    return GitHubClient(token="t", owner="U2NyaWJl", repo="vault")


def _entry(sha: str, name: str, when: str) -> dict:
    return {"sha256": sha, "filename": name, "ingested_at": when}


@respx.mock
async def test_add_creates_manifest_when_absent():
    respx.get(BASE).mock(return_value=httpx.Response(404))
    put = respx.put(BASE).mock(return_value=httpx.Response(201, json={"commit": {"sha": "c1"}}))

    await manifest.add(_vault(), _entry("aaa", "acta.pdf", "2026-07-14T10:00:00"))

    import base64
    written = json.loads(base64.b64decode(json.loads(put.calls[0].request.content)["content"]))
    assert len(written) == 1
    assert written[0]["filename"] == "acta.pdf"


@respx.mock
async def test_add_dedupes_by_hash():
    """El mismo archivo, reingerido, actualiza su fila en vez de duplicarla."""
    import base64
    existing = [_entry("aaa", "viejo.pdf", "2026-07-14T09:00:00")]
    respx.get(BASE).mock(return_value=httpx.Response(200, json={
        "content": base64.b64encode(json.dumps(existing).encode()).decode(), "sha": "s1",
    }))
    put = respx.put(BASE).mock(return_value=httpx.Response(200, json={"commit": {"sha": "c2"}}))

    await manifest.add(_vault(), _entry("aaa", "nuevo.pdf", "2026-07-14T11:00:00"))

    written = json.loads(base64.b64decode(json.loads(put.calls[0].request.content)["content"]))
    assert len(written) == 1, "un hash repetido no debe crear una segunda fila"
    assert written[0]["filename"] == "nuevo.pdf"


@respx.mock
async def test_load_survives_corrupt_manifest():
    import base64
    respx.get(BASE).mock(return_value=httpx.Response(200, json={
        "content": base64.b64encode(b"esto no es json").decode(), "sha": "s1",
    }))

    assert await manifest.load(_vault()) == []
