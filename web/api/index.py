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
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

GITHUB_API = "https://api.github.com"

AGENT_WAKE_SECRET = os.environ.get("AGENT_WAKE_SECRET", "")
DASHBOARD_API_TOKEN = os.environ.get("DASHBOARD_API_TOKEN", "")
GITHUB_DISPATCH_TOKEN = os.environ.get("GITHUB_DISPATCH_TOKEN", "")
VAULT_GITHUB_TOKEN = os.environ.get("VAULT_GITHUB_TOKEN", "")
AGENT_REPO_OWNER = os.environ.get("AGENT_REPO_OWNER", "")
AGENT_REPO_NAME = os.environ.get("AGENT_REPO_NAME", "")
VAULT_REPO_OWNER = os.environ.get("VAULT_REPO_OWNER", "")
VAULT_REPO_NAME = os.environ.get("VAULT_REPO_NAME", "")
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "")

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

REAL_ROUTES = {"/", "/wake", "/health", "/api/status", "/api/logs", "/api/tasks"}
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
