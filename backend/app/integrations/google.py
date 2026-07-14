"""Drive y Calendar del agente.

Drive es su almacén de archivos; Calendar, su registro de reuniones y eventos.
El scope es `drive.file`: el agente solo ve lo que él mismo crea. No puede leer
archivos que subas tú a mano — los documentos entran por correo, no por Drive.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

FOLDER_MIME = "application/vnd.google-apps.folder"


@dataclass
class DriveFile:
    id: str
    name: str
    link: str


class GoogleClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        root_folder_id: str = "",
        calendar_id: str = "primary",
        client: httpx.AsyncClient | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.root_folder_id = root_folder_id
        self.calendar_id = calendar_id
        self._client = client
        self._access_token = ""
        self._expires_at = 0.0

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _token(self) -> str:
        # El access token dura 1 h; se renueva con 60 s de margen para no perder
        # una llamada por caducar en pleno vuelo.
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        client = await self._http()
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data["expires_in"]
        return self._access_token

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = await self._http()
        headers = {"Authorization": f"Bearer {await self._token()}", **kwargs.pop("headers", {})}
        resp = await client.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp

    # ── Drive ────────────────────────────────────────────────────────────

    async def upload(
        self, name: str, content: bytes, mime: str = "text/plain", folder_id: str = ""
    ) -> DriveFile:
        metadata = {"name": name, "parents": [folder_id or self.root_folder_id]}
        boundary = "u2scribe-boundary"
        body = b"".join([
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
            json.dumps(metadata).encode(),
            f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--".encode(),
        ])
        resp = await self._request(
            "POST",
            f"{DRIVE_UPLOAD}?uploadType=multipart&fields=id,name,webViewLink",
            content=body,
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        )
        data = resp.json()
        return DriveFile(id=data["id"], name=data["name"], link=data.get("webViewLink", ""))

    async def ensure_folder(self, name: str, parent_id: str = "") -> str:
        parent = parent_id or self.root_folder_id
        query = f"name='{name}' and mimeType='{FOLDER_MIME}' and '{parent}' in parents and trashed=false"
        resp = await self._request(
            "GET", f"{DRIVE_API}/files", params={"q": query, "fields": "files(id)"}
        )
        files = resp.json().get("files", [])
        if files:
            return files[0]["id"]

        resp = await self._request(
            "POST",
            f"{DRIVE_API}/files",
            params={"fields": "id"},
            json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
        )
        return resp.json()["id"]

    async def list_folder(self, folder_id: str = "") -> list[DriveFile]:
        parent = folder_id or self.root_folder_id
        resp = await self._request(
            "GET",
            f"{DRIVE_API}/files",
            params={
                "q": f"'{parent}' in parents and trashed=false",
                "fields": "files(id,name,webViewLink)",
            },
        )
        return [
            DriveFile(id=f["id"], name=f["name"], link=f.get("webViewLink", ""))
            for f in resp.json().get("files", [])
        ]

    async def delete(self, file_id: str) -> None:
        await self._request("DELETE", f"{DRIVE_API}/files/{file_id}")

    # ── Calendar ─────────────────────────────────────────────────────────

    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
    ) -> dict:
        resp = await self._request(
            "POST",
            f"{CALENDAR_API}/calendars/{self.calendar_id}/events",
            json={
                "summary": summary,
                "description": description,
                "location": location,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
        return resp.json()

    async def upcoming_events(self, since: datetime, limit: int = 20) -> list[dict]:
        resp = await self._request(
            "GET",
            f"{CALENDAR_API}/calendars/{self.calendar_id}/events",
            params={
                "timeMin": since.isoformat(),
                "maxResults": limit,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        return resp.json().get("items", [])

    async def delete_event(self, event_id: str) -> None:
        await self._request(
            "DELETE", f"{CALENDAR_API}/calendars/{self.calendar_id}/events/{event_id}"
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
