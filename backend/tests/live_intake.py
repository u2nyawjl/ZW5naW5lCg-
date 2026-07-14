"""Prueba real del núcleo de entrada: correo → LLM → pipeline → Drive → bóveda.

    docker compose run --rm --no-deps -v ./backend:/app api python -m tests.live_intake
"""

import asyncio
from pathlib import Path

from app.agent.brain import Brain
from app.agent.intake import process_inbox
from app.comms.email import EmailClient
from app.config import get_settings
from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient
from app.security.virustotal import VirusTotalClient


async def main() -> None:
    s = get_settings()

    vault = GitHubClient(s.vault_github_token, s.vault_repo_owner, s.vault_repo_name, s.vault_repo_branch)
    mission_note = await vault.read_note("system/mission.md")
    mission = mission_note.content if mission_note else "Secretario general."

    brain = Brain(s.github_models_token, s.github_models_base_url, s.github_models_model)
    google = GoogleClient(s.google_oauth_client_id, s.google_oauth_client_secret,
                          s.google_oauth_refresh_token, s.gdrive_root_folder_id, s.google_calendar_id)
    mail = EmailClient(s.gmail_address, s.imap_password, s.imap_host, s.imap_port,
                       s.smtp_host, s.smtp_port)
    vt = VirusTotalClient(s.virustotal_api_key)

    print("Procesando bandeja de entrada...\n")
    result = await process_inbox(
        s, brain=brain, vault=vault, google=google, mail=mail, vt_client=vt, mission=mission
    )

    print(f"  Correos procesados ... {result.processed}")
    print(f"  Relevantes ........... {result.relevant}")
    print(f"  Archivos guardados ... {result.files_stored}")
    print(f"  Archivos bloqueados .. {result.files_blocked}")
    for n in result.notes:
        print(f"  Nota ................. {n}")
    for e in result.errors:
        print(f"  ⚠️  {e}")

    print("\nManifiesto (sistema de archivos del agente):")
    from app.vault import manifest
    for f in await manifest.load(vault):
        print(f"  · {f['filename']} · VT {f['vt_status']} · {f['decision']} · "
              f"{'en Drive' if f['drive_link'] else 'solo registro'}")

    for c in (brain, google, vault, vt):
        await c.aclose()


if __name__ == "__main__":
    asyncio.run(main())
