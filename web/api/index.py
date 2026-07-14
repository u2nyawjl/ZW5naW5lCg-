"""La puerta HTTP de U2NyaWJl (Vercel).

Es deliberadamente tonta: recibe, valida, y delega. Nunca hace el trabajo pesado.
Llamar a VirusTotal y al LLM dentro de una función serverless agotaría el timeout;
eso corre en GitHub Actions, que no tiene límite de tiempo.

  POST /wake            Apps Script avisa de un correo urgente → despierta al agente
  GET  /health          Vivo o no
  GET  /api/status      Estado para el HUD del dashboard
  GET  /api/vault/*     Lectura de la bóveda (token)
  GET  /api/logs        Timeline de latidos (token)
  GET  /api/tasks       Issues abiertos (token)

Cualquier ruta fuera de esa lista se considera un sondeo y se reporta. Ver abajo.
"""

import base64
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

GITHUB_API = "https://api.github.com"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
IDENTITY_AUD = ("https://identitytoolkit.googleapis.com/"
                "google.identity.identitytoolkit.v1.IdentityToolkit")

AGENT_WAKE_SECRET = os.environ.get("AGENT_WAKE_SECRET", "")
DASHBOARD_API_TOKEN = os.environ.get("DASHBOARD_API_TOKEN", "")
GITHUB_DISPATCH_TOKEN = os.environ.get("GITHUB_DISPATCH_TOKEN", "")
VAULT_GITHUB_TOKEN = os.environ.get("VAULT_GITHUB_TOKEN", "")
AGENT_REPO_OWNER = os.environ.get("AGENT_REPO_OWNER", "")
AGENT_REPO_NAME = os.environ.get("AGENT_REPO_NAME", "")
VAULT_REPO_OWNER = os.environ.get("VAULT_REPO_OWNER", "")
VAULT_REPO_NAME = os.environ.get("VAULT_REPO_NAME", "")
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "")

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REFRESH_TOKEN = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

FIREBASE_SERVICE_ACCOUNT_B64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64", "")

app = FastAPI(title="U2NyaWJl // gateway", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Agent-Secret"],
)


def client_ip(request: Request) -> str:
    # Detrás del proxy de Vercel, request.client es la red interna.
    return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "?"


def require_dashboard(authorization: str | None) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    # compare_digest y no ==: una comparación normal filtra el token por tiempo de respuesta.
    if not DASHBOARD_API_TOKEN or not hmac.compare_digest(token, DASHBOARD_API_TOKEN):
        raise HTTPException(status_code=401, detail="No autorizado")


async def github(path: str, token: str, params: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15.0) as client:
        return await client.get(
            f"{GITHUB_API}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params=params or {},
        )


async def dispatch(event_type: str, payload: dict) -> bool:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{AGENT_REPO_OWNER}/{AGENT_REPO_NAME}/dispatches",
            headers={
                "Authorization": f"Bearer {GITHUB_DISPATCH_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"event_type": event_type, "client_payload": payload},
        )
        return resp.status_code == 204


# ── Login: token del dashboard → sesión de Firebase ───────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _mint_custom_token() -> str:
    """Firma un custom token de Firebase con el service account.

    El navegador lo canjea con signInWithCustomToken; las reglas de Firestore
    exigen esa sesión para leer. Así el token del dashboard nunca toca Firestore
    directamente y las reglas gatean todo acceso.
    """
    sa = json.loads(base64.b64decode(FIREBASE_SERVICE_ACCOUNT_B64))
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "iss": sa["client_email"],
        "sub": sa["client_email"],
        "aud": IDENTITY_AUD,
        "uid": "dashboard",
        "iat": now,
        "exp": now + 3600,
    }).encode())
    signing_input = f"{header}.{payload}".encode()
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(signature)}"


@app.post("/auth")
async def auth(authorization: str | None = Header(default=None)):
    require_dashboard(authorization)
    if not FIREBASE_SERVICE_ACCOUNT_B64:
        raise HTTPException(status_code=503, detail="Firebase no configurado")
    return {"firebase_token": _mint_custom_token()}


# ── Despertar ────────────────────────────────────────────────────────────

@app.post("/wake")
async def wake(request: Request, x_agent_secret: str = Header(default="")):
    """Apps Script llama aquí cuando entra un correo con la etiqueta `agent-wake`."""
    if not AGENT_WAKE_SECRET or not hmac.compare_digest(x_agent_secret, AGENT_WAKE_SECRET):
        # Sin esto, cualquiera que descubra la URL podría despertar al agente a voluntad.
        raise HTTPException(status_code=403, detail="Secreto inválido")

    try:
        body = await request.json()
    except Exception:
        body = {}

    ok = await dispatch("wake", {
        "source": body.get("source", "gmail"),
        "reason": body.get("reason", "correo etiquetado"),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    if not ok:
        raise HTTPException(status_code=502, detail="No se pudo despertar al agente")
    return {"status": "despertado"}


# ── Estado ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


@app.get("/api/status")
async def status(authorization: str | None = Header(default=None)):
    require_dashboard(authorization)
    resp = await github(
        f"/repos/{AGENT_REPO_OWNER}/{AGENT_REPO_NAME}/actions/runs",
        GITHUB_DISPATCH_TOKEN,
        {"per_page": 1},
    )
    runs = resp.json().get("workflow_runs", []) if resp.status_code == 200 else []
    last = runs[0] if runs else None
    return {
        "agent_core": "online",
        "honeypot": "armed",
        "last_heartbeat": {
            "at": last["created_at"],
            "trigger": last["event"],
            "conclusion": last["conclusion"],
            "url": last["html_url"],
        } if last else None,
    }


# ── Lectura de la bóveda ─────────────────────────────────────────────────

@app.get("/api/vault/{path:path}")
async def vault(path: str, authorization: str | None = Header(default=None)):
    require_dashboard(authorization)
    resp = await github(
        f"/repos/{VAULT_REPO_OWNER}/{VAULT_REPO_NAME}/contents/{path}", VAULT_GITHUB_TOKEN
    )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="No existe en la bóveda")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="La bóveda no responde")

    data = resp.json()
    if isinstance(data, list):
        return {"type": "folder", "entries": [
            {"name": e["name"], "path": e["path"], "type": e["type"]} for e in data
        ]}
    return {
        "type": "file",
        "path": data["path"],
        "content": base64.b64decode(data["content"]).decode("utf-8", errors="replace"),
    }


@app.get("/api/logs")
async def logs(authorization: str | None = Header(default=None), limit: int = 20):
    require_dashboard(authorization)
    resp = await github(
        f"/repos/{AGENT_REPO_OWNER}/{AGENT_REPO_NAME}/actions/runs",
        GITHUB_DISPATCH_TOKEN,
        {"per_page": limit},
    )
    if resp.status_code != 200:
        return {"events": []}
    return {"events": [
        {
            "ts": r["created_at"],
            "type": f"heartbeat.{r['event']}",
            "level": "info" if r["conclusion"] == "success" else "alert",
            "message": f"Latido ({r['event']}): {r['conclusion'] or r['status']}",
            "url": r["html_url"],
        }
        for r in resp.json().get("workflow_runs", [])
    ]}


async def _google_token(http: httpx.AsyncClient) -> str:
    tok = await http.post(GOOGLE_TOKEN_URL, data={
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "refresh_token": GOOGLE_OAUTH_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    if tok.status_code != 200:
        raise HTTPException(status_code=502, detail="Google no renovó el token")
    return tok.json()["access_token"]


@app.get("/api/file")
async def file(id: str, authorization: str | None = Header(default=None)):
    """Sirve los bytes de un archivo de Drive del agente, para verlo en el dashboard."""
    require_dashboard(authorization)
    if not GOOGLE_OAUTH_REFRESH_TOKEN:
        raise HTTPException(status_code=503, detail="Drive no configurado")
    async with httpx.AsyncClient(timeout=30.0) as http:
        access = await _google_token(http)
        resp = await http.get(
            f"https://www.googleapis.com/drive/v3/files/{id}",
            params={"alt": "media"},
            headers={"Authorization": f"Bearer {access}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="No se pudo leer el archivo")
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
    )


@app.get("/api/calendar")
async def calendar(authorization: str | None = Header(default=None), days: int = 21):
    """Agenda real del Google Calendar del agente. Cada evento enlaza al calendario."""
    require_dashboard(authorization)
    if not GOOGLE_OAUTH_REFRESH_TOKEN:
        return {"events": [], "detail": "Calendar no configurado"}

    async with httpx.AsyncClient(timeout=15.0) as http:
        access = await _google_token(http)
        now = datetime.now(timezone.utc)
        resp = await http.get(
            f"{CALENDAR_API}/calendars/{GOOGLE_CALENDAR_ID}/events",
            headers={"Authorization": f"Bearer {access}"},
            params={
                "timeMin": now.isoformat(),
                "timeMax": (now + timedelta(days=days)).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 50,
            },
        )
    if resp.status_code != 200:
        return {"events": []}

    return {"events": [
        {
            "id": e.get("id"),
            "summary": e.get("summary", "(sin título)"),
            "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
            "all_day": "date" in e.get("start", {}),
            "location": e.get("location", ""),
            "link": e.get("htmlLink", ""),
        }
        for e in resp.json().get("items", [])
    ]}


@app.get("/api/tasks")
async def tasks(authorization: str | None = Header(default=None)):
    require_dashboard(authorization)
    resp = await github(
        f"/repos/{AGENT_REPO_OWNER}/{AGENT_REPO_NAME}/issues",
        GITHUB_DISPATCH_TOKEN,
        {"state": "open", "per_page": 50},
    )
    if resp.status_code != 200:
        return {"tasks": []}
    return {"tasks": [
        {
            "number": i["number"],
            "title": i["title"],
            "labels": [lab["name"] for lab in i["labels"]],
            "url": i["html_url"],
        }
        for i in resp.json() if "pull_request" not in i
    ]}


# ── Rutas desconocidas ───────────────────────────────────────────────────
#
# Este código es público. Publicar una lista de rutas señuelo sería regalarle al
# atacante justo lo que debe evitar. Así que no hay lista: se declaran las rutas
# reales y CUALQUIER otra cosa se trata como sondeo. No hay nada que filtrar, y
# además cubre las rutas que no se me ocurrieron.

REAL_ROUTES = {"/", "/auth", "/wake", "/health", "/api/status", "/api/logs",
               "/api/tasks", "/api/calendar", "/api/file"}
REAL_PREFIXES = ("/api/vault/",)

# Ruido de fondo de cualquier navegador o crawler: no merece una alerta.
IGNORED = {"/favicon.ico", "/robots.txt", "/apple-touch-icon.png",
           "/apple-touch-icon-precomposed.png", "/sitemap.xml"}

# Best-effort: cada instancia caliente recuerda lo que ya reportó, para que un escaneo
# automatizado no dispare mil workflows. Las funciones serverless no comparten memoria,
# así que no es un rate limit fuerte — la deduplicación de verdad la hace el workflow,
# que agrupa todos los sondeos del día en un único issue.
_reported: set[str] = set()


@app.middleware("http")
async def watch_unknown_routes(request: Request, call_next):
    path = request.url.path

    if path in REAL_ROUTES or path.startswith(REAL_PREFIXES) or path in IGNORED:
        return await call_next(request)

    ip = client_ip(request)
    key = f"{ip}:{path}"
    if key not in _reported:
        _reported.add(key)
        await dispatch("trip", {
            "ip": ip,
            "path": path,
            "method": request.method,
            "user_agent": request.headers.get("user-agent", "?"),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    # Un 403 confirmaría que hay algo detrás. El 404 genérico no le regala nada.
    return JSONResponse(status_code=404, content={"detail": "Not Found"})
