"""Cliente ligero de Firestore vía REST + JWT del service account.

Sin firebase-admin (que arrastra grpc y ~50 MB): solo firma un JWT con la clave
privada y habla con la API REST. El agente escribe aquí; el dashboard lee en vivo
directamente desde el navegador, sin pasar por ninguna función.
"""

import base64
import json
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/datastore"


def _b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _to_value(v) -> dict:
    """Convierte un valor Python al formato de Firestore REST."""
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_to_value(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _to_value(x) for k, x in v.items()}}}
    return {"stringValue": str(v)}


def _to_fields(d: dict) -> dict:
    return {k: _to_value(v) for k, v in d.items()}


class FirestoreClient:
    def __init__(self, service_account_b64: str, project_id: str,
                 client: httpx.AsyncClient | None = None):
        self._sa = json.loads(base64.b64decode(service_account_b64))
        self.project_id = project_id
        self._client = client
        self._access_token = ""
        self._expires_at = 0.0
        self._base = (
            f"https://firestore.googleapis.com/v1/projects/{project_id}"
            "/databases/(default)/documents"
        )

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token

        now = int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claim = _b64url(json.dumps({
            "iss": self._sa["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }).encode())
        signing_input = header + b"." + claim

        key = serialization.load_pem_private_key(self._sa["private_key"].encode(), password=None)
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt = signing_input + b"." + _b64url(signature)

        client = await self._http()
        resp = await client.post(TOKEN_URL, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt.decode(),
        })
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.time() + data["expires_in"]
        return self._access_token

    async def set(self, path: str, fields: dict) -> None:
        """Upsert de un documento en `path` (ej. 'status/current')."""
        client = await self._http()
        resp = await client.patch(
            f"{self._base}/{path}",
            headers={"Authorization": f"Bearer {await self._token()}"},
            json={"fields": _to_fields(fields)},
        )
        resp.raise_for_status()

    async def add(self, collection: str, fields: dict) -> None:
        """Crea un documento con ID automático (para logs append-only)."""
        client = await self._http()
        resp = await client.post(
            f"{self._base}/{collection}",
            headers={"Authorization": f"Bearer {await self._token()}"},
            json={"fields": _to_fields(fields)},
        )
        resp.raise_for_status()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
