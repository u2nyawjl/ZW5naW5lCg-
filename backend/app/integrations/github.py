"""GitHub como sustrato del agente.

- La **bóveda** es un repo privado: las notas .md se leen y escriben por la Contents API.
- Las **tareas** son Issues del repo del agente: tablero, etiquetas, historial y push al
  móvil gratis, sin construir un sistema de notificaciones.

Los tokens NO son intercambiables:
- Bóveda   → VAULT_GITHUB_TOKEN (Contents: rw sobre el repo privado)
- Issues   → GITHUB_TOKEN, el que Actions inyecta solo (trae Issues: write)
- Despertar→ GITHUB_DISPATCH_TOKEN (Contents: rw sobre el repo del agente)
"""

import asyncio
import base64
import time
from dataclasses import dataclass

import httpx

API = "https://api.github.com"


@dataclass
class VaultNote:
    path: str
    content: str
    sha: str      # necesario para sobrescribir: sin él, la Contents API rechaza el update


class GitHubClient:
    def __init__(
        self, token: str, owner: str, repo: str, branch: str = "main",
        client: httpx.AsyncClient | None = None,
    ):
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self._token = token
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        client = await self._http()
        return await client.request(
            method,
            f"{API}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            **kwargs,
        )

    # ── Bóveda ───────────────────────────────────────────────────────────

    async def read_note(self, path: str, fresh: bool = False) -> VaultNote | None:
        # La Contents API cachea: tras escribir, una lectura puede devolver 404 durante
        # unos segundos. `fresh` añade un parámetro irrelevante para esquivar la caché.
        params: dict[str, str] = {"ref": self.branch}
        if fresh:
            params["_"] = str(time.time_ns())

        resp = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/contents/{path}", params=params
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return VaultNote(
            path=path,
            content=base64.b64decode(data["content"]).decode("utf-8"),
            sha=data["sha"],
        )

    async def delete_note(self, path: str, message: str) -> bool:
        """Borra una nota. False si ya no estaba (borrar dos veces no es un fallo)."""
        existing = await self.read_note(path, fresh=True)
        if not existing:
            return False
        resp = await self._request(
            "DELETE", f"/repos/{self.owner}/{self.repo}/contents/{path}",
            json={"message": message, "sha": existing.sha, "branch": self.branch},
        )
        resp.raise_for_status()
        return True

    async def write_note(self, path: str, content: str, message: str, attempts: int = 3) -> str:
        """Crea o sobrescribe una nota. Devuelve el sha del commit.

        GitHub tiene consistencia eventual: la lectura previa puede decir que la nota no
        existe cuando sí existe, y entonces el PUT sin `sha` se rechaza con 409/422. Cuando
        eso pasa, se relee esquivando la caché y se reintenta. Sin esto, el agente perdería
        escrituras de forma intermitente e inexplicable.
        """
        encoded = base64.b64encode(content.encode()).decode()
        sha: str | None = None
        existing = await self.read_note(path)
        if existing:
            sha = existing.sha

        for attempt in range(attempts):
            payload = {"message": message, "content": encoded, "branch": self.branch}
            if sha:
                payload["sha"] = sha

            resp = await self._request(
                "PUT", f"/repos/{self.owner}/{self.repo}/contents/{path}", json=payload
            )
            if resp.status_code < 300:
                return resp.json()["commit"]["sha"]

            if resp.status_code not in (409, 422) or attempt == attempts - 1:
                resp.raise_for_status()

            await asyncio.sleep(0.5 * (attempt + 1))
            current = await self.read_note(path, fresh=True)
            sha = current.sha if current else None

        raise RuntimeError(f"no se pudo escribir {path} tras {attempts} intentos")

    async def list_notes(self, folder: str = "") -> list[str]:
        resp = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/contents/{folder}",
            params={"ref": self.branch},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [f["path"] for f in resp.json() if f["type"] == "file"]

    async def tree(self) -> list[dict]:
        """La bóveda entera —rutas, tipo y sha— en UNA petición.

        La Contents API obliga a una petición por carpeta; esta devuelve el repo
        completo. Importa por dos motivos: el indexador necesita el sha del blob
        para saber qué cambió (cambia si y solo si cambia el contenido), y el
        shell necesita el árbol para que `ls`/`find`/`tree` no cuesten N llamadas.
        """
        resp = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/git/trees/{self.branch}",
            params={"recursive": "1"},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return [
            {"path": e["path"], "type": e["type"], "sha": e["sha"], "size": e.get("size", 0)}
            for e in data.get("tree", [])
        ]

    # ── Tareas (Issues) ──────────────────────────────────────────────────

    async def create_task(self, title: str, body: str, labels: list[str] | None = None) -> dict:
        resp = await self._request(
            "POST", f"/repos/{self.owner}/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels or []},
        )
        resp.raise_for_status()
        return resp.json()

    async def open_tasks(self, label: str = "") -> list[dict]:
        params = {"state": "open", "per_page": 50}
        if label:
            params["labels"] = label
        resp = await self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/issues", params=params
        )
        resp.raise_for_status()
        # La API devuelve los PRs mezclados con los issues; los PRs no son tareas.
        return [i for i in resp.json() if "pull_request" not in i]

    async def comment_task(self, number: int, body: str) -> dict:
        resp = await self._request(
            "POST", f"/repos/{self.owner}/{self.repo}/issues/{number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

    async def close_task(self, number: int, reason: str = "completed") -> dict:
        resp = await self._request(
            "PATCH", f"/repos/{self.owner}/{self.repo}/issues/{number}",
            json={"state": "closed", "state_reason": reason},
        )
        resp.raise_for_status()
        return resp.json()

    # ── Despertar ────────────────────────────────────────────────────────

    async def dispatch(self, event_type: str, payload: dict | None = None) -> None:
        resp = await self._request(
            "POST", f"/repos/{self.owner}/{self.repo}/dispatches",
            json={"event_type": event_type, "client_payload": payload or {}},
        )
        resp.raise_for_status()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
