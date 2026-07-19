from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Sistema ---
    agent_name: str = "U2NyaWJl"
    log_level: str = "INFO"
    tz: str = "America/Santiago"

    # --- Rutas (solo desarrollo local; en Actions todo es efímero) ---
    vault_dir: Path = Path("/app/vault")
    data_dir: Path = Path("/app/data")
    quarantine_dir: Path = Path("/app/quarantine")
    logs_dir: Path = Path("/app/logs")

    # --- Dashboard ---
    dashboard_api_token: str = ""
    cors_allowed_origins: str = "http://localhost:5173"

    # --- IA ---
    github_models_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    github_models_model: str = "openai/gpt-4.1-mini"
    agent_max_llm_calls_per_hour: int = 20

    # --- Seguridad de archivos ---
    virustotal_api_key: str = ""
    vt_upload_unknown: bool = False
    vt_unknown_policy: str = "parse_flagged"
    max_file_size_mb: int = 25
    max_uncompressed_mb: int = 200
    max_pdf_pages: int = 500

    # --- Unstructured (lectura amplia de documentos vía API: pptx, docx, imágenes…) ---
    unstructured_api_key: str = ""
    unstructured_api_url: str = "https://api.unstructuredapp.io/general/v0/general"

    # --- Bóveda (repo privado de GitHub) ---
    vault_repo_owner: str = ""
    vault_repo_name: str = ""
    vault_repo_branch: str = "main"
    vault_github_token: str = ""

    # --- Repo del agente (Actions + Issues como tareas) ---
    agent_repo_owner: str = ""
    agent_repo_name: str = ""
    github_dispatch_token: str = ""
    # Dentro de Actions este lo inyecta la plataforma y trae permiso sobre Issues.
    github_token: str = ""
    tasks_via_issues: bool = True

    # --- Google ---
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""
    gdrive_root_folder_id: str = ""
    google_calendar_id: str = "primary"

    # --- Firestore ---
    firebase_project_id: str = ""
    firebase_service_account_b64: str = ""    # el JSON del service account, en base64
    # Bucket donde esperan los archivos subidos a mano hasta que VirusTotal los
    # mire. Vacío = no hay cola: la subida se rechaza en vez de guardarse sin escanear.
    firebase_storage_bucket: str = ""

    # --- Correo ---
    gmail_address: str = ""
    owner_email: str = ""
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_password: str = ""
    gmail_wake_label: str = "agent-wake"
    # projects/<proyecto>/topics/<topic>. Vacío = sin timbre: el correo entra
    # cuando pase el cron, no al llegar.
    gmail_pubsub_topic: str = ""

    # --- Honeypot ---
    honeypot_enabled: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def issues_token(self) -> str:
        """En Actions manda el GITHUB_TOKEN de la plataforma; en local, el PAT de dispatch."""
        return self.github_token or self.github_dispatch_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
