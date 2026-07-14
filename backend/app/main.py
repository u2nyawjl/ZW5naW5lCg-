from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="U2NyaWJl // Agente Secretario y Documentador",
    version="0.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "version": app.version,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@app.get("/api/status")
def status() -> dict:
    """Estado de las integraciones. Alimenta la barra HUD del dashboard."""
    return {
        "agent_core": "online",
        "honeypot": "armed" if settings.honeypot_enabled else "disabled",
        "integrations": {
            "github_models": bool(settings.github_models_token),
            "virustotal": bool(settings.virustotal_api_key),
            "dashboard_auth": bool(settings.dashboard_api_token),
        },
        "vt_upload_unknown": settings.vt_upload_unknown,
    }
