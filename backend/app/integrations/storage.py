"""Firebase Storage: el compás de espera de los archivos subidos a mano.

Un archivo que acaba de subir Nico todavía no ha pasado por VirusTotal, y la
regla del proyecto es que nada sin escanear sube a Drive. Pero tampoco puede
quedarse en Vercel, que no guarda nada entre peticiones, ni en la bóveda, que es
git y guardaría esos bytes en el historial para siempre.

Así que esperan aquí, y se borran en cuanto el latido los procesa.
"""

import base64
import json
import time
import urllib.parse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
API = "https://storage.googleapis.com/storage/v1"
UPLOAD_API = "https://storage.googleapis.com/upload/storage/v1"


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


class StorageClient:
    def __init__(self, service_account_b64: str, bucket: str,
                 client: httpx.AsyncClient | None = None):
        self._sa = json.loads(base64.b64decode(service_account_b64)) if service_account_b64 else {}
        self.bucket = bucket
        self._client = client
        self._token_cache = ""
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._sa and self.bucket)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _token(self) -> str:
        if self._token_cache and time.time() < self._expires_at - 60:
            return self._token_cache
        now = int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claim = _b64url(json.dumps({
            "iss": self._sa["client_email"], "scope": SCOPE,
            "aud": TOKEN_URL, "iat": now, "exp": now + 3600,
        }).encode())
        signing_input = header + b"." + claim
        key = serialization.load_pem_private_key(self._sa["private_key"].encode(), password=None)
        sig = _b64url(key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256()))
        http = await self._http()
        resp = await http.post(TOKEN_URL, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": (signing_input + b"." + sig).decode(),
        })
        resp.raise_for_status()
        data = resp.json()
        self._token_cache = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._token_cache

    async def _auth(self) -> dict:
        return {"Authorization": f"Bearer {await self._token()}"}

    async def put(self, name: str, content: bytes, mime: str = "application/octet-stream") -> None:
        http = await self._http()
        resp = await http.post(
            f"{UPLOAD_API}/b/{self.bucket}/o",
            params={"uploadType": "media", "name": name},
            headers={**await self._auth(), "Content-Type": mime},
            content=content,
        )
        resp.raise_for_status()

    async def get(self, name: str) -> bytes | None:
        """Los bytes, o None si ya no está (procesado y borrado por otro latido)."""
        http = await self._http()
        resp = await http.get(
            f"{API}/b/{self.bucket}/o/{urllib.parse.quote(name, safe='')}",
            params={"alt": "media"}, headers=await self._auth(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    async def delete(self, name: str) -> bool:
        http = await self._http()
        resp = await http.delete(
            f"{API}/b/{self.bucket}/o/{urllib.parse.quote(name, safe='')}",
            headers=await self._auth(),
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True
