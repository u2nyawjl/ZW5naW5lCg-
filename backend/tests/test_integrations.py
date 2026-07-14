import base64
import json

import httpx
import pytest
import respx

from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient

pytestmark = pytest.mark.asyncio


def _google() -> GoogleClient:
    return GoogleClient(
        client_id="cid",
        client_secret="csecret",
        refresh_token="rtok",
        root_folder_id="folder123",
    )


def _mock_token(expires_in: int = 3600) -> None:
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": expires_in})
    )


@respx.mock
async def test_google_reuses_access_token_across_calls():
    """Renovar el token en cada llamada gastaría cuota y latencia para nada."""
    _mock_token()
    files = respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    g = _google()

    await g.list_folder()
    await g.list_folder()

    assert respx.calls.call_count == 3  # 1 token + 2 llamadas
    assert files.call_count == 2


@respx.mock
async def test_google_refreshes_token_when_it_is_about_to_expire():
    _mock_token(expires_in=30)  # dentro del margen de 60 s
    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    g = _google()

    await g.list_folder()
    await g.list_folder()

    tokens = [c for c in respx.calls if c.request.url.host == "oauth2.googleapis.com"]
    assert len(tokens) == 2, "un token a punto de caducar debe renovarse antes de usarse"


@respx.mock
async def test_drive_upload_targets_the_agent_folder():
    _mock_token()
    upload = respx.post("https://www.googleapis.com/upload/drive/v3/files").mock(
        return_value=httpx.Response(200, json={"id": "f1", "name": "acta.md", "webViewLink": "u"})
    )
    g = _google()

    result = await g.upload("acta.md", b"# acta", mime="text/markdown")

    assert result.id == "f1"
    body = upload.calls[0].request.content.decode()
    assert '"parents": ["folder123"]' in body, "el archivo debe caer en la carpeta del agente"


@respx.mock
async def test_vault_write_sends_sha_when_the_note_already_exists():
    """Sin el sha, la Contents API rechaza el update con un 409."""
    respx.get(
        "https://api.github.com/repos/U2NyaWJl/vault/contents/notas/hola.md"
    ).mock(
        return_value=httpx.Response(
            200, json={"content": base64.b64encode(b"viejo").decode(), "sha": "abc123"}
        )
    )
    put = respx.put(
        "https://api.github.com/repos/U2NyaWJl/vault/contents/notas/hola.md"
    ).mock(return_value=httpx.Response(200, json={"commit": {"sha": "commit1"}}))

    gh = GitHubClient(token="t", owner="U2NyaWJl", repo="vault")
    await gh.write_note("notas/hola.md", "nuevo", "actualiza nota")

    assert json.loads(put.calls[0].request.content)["sha"] == "abc123"


@respx.mock
async def test_vault_write_omits_sha_for_a_new_note():
    respx.get(
        "https://api.github.com/repos/U2NyaWJl/vault/contents/notas/nueva.md"
    ).mock(return_value=httpx.Response(404))
    put = respx.put(
        "https://api.github.com/repos/U2NyaWJl/vault/contents/notas/nueva.md"
    ).mock(return_value=httpx.Response(201, json={"commit": {"sha": "commit2"}}))

    gh = GitHubClient(token="t", owner="U2NyaWJl", repo="vault")
    await gh.write_note("notas/nueva.md", "hola", "crea nota")

    assert "sha" not in json.loads(put.calls[0].request.content)


@respx.mock
async def test_open_tasks_excludes_pull_requests():
    """La API mezcla PRs con issues: un PR no es una tarea del agente."""
    respx.get("https://api.github.com/repos/U2NyaWJl/engine/issues").mock(
        return_value=httpx.Response(200, json=[
            {"number": 1, "title": "Tarea real"},
            {"number": 2, "title": "Un PR", "pull_request": {"url": "..."}},
        ])
    )

    gh = GitHubClient(token="t", owner="U2NyaWJl", repo="engine")
    tasks = await gh.open_tasks()

    assert [t["number"] for t in tasks] == [1]
