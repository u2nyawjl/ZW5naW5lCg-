"""Prueba contra las APIs reales: bóveda, issues y Drive.

    docker compose run --rm --no-deps -v ./backend:/app api python -m tests.live_integrations
"""

import asyncio
import os
from datetime import datetime, timezone

import httpx

from app.integrations.github import GitHubClient
from app.integrations.google import GoogleClient


async def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # ── Bóveda ───────────────────────────────────────────────────────────
    vault = GitHubClient(
        token=os.environ["VAULT_GITHUB_TOKEN"],
        owner=os.environ["VAULT_REPO_OWNER"],
        repo=os.environ["VAULT_REPO_NAME"],
        branch=os.environ.get("VAULT_REPO_BRANCH", "main"),
    )
    try:
        sha = await vault.write_note(
            "system/_conexion.md",
            f"---\ntipo: system\nactualizado: {stamp}\n---\n\n"
            f"# Prueba de conexión\n\nEl agente escribió esta nota el {stamp} UTC.\n",
            "chore: prueba de conexión del agente",
        )
        print(f"✅ BÓVEDA escritura   · commit {sha[:8]} · system/_conexion.md")
        note = await vault.read_note("system/_conexion.md")
        print(f"✅ BÓVEDA lectura     · {len(note.content)} caracteres")
    except httpx.HTTPStatusError as e:
        print(f"❌ BÓVEDA · HTTP {e.response.status_code}: {e.response.json().get('message')}")
    finally:
        await vault.aclose()

    # ── Issues (tareas) ──────────────────────────────────────────────────
    engine = GitHubClient(
        token=os.environ["GITHUB_DISPATCH_TOKEN"],
        owner=os.environ["AGENT_REPO_OWNER"],
        repo=os.environ["AGENT_REPO_NAME"],
    )
    try:
        issue = await engine.create_task(
            title="Prueba de conexión del agente",
            body=f"Creado automáticamente el {stamp} UTC. Puedes cerrarlo.",
        )
        print(f"✅ ISSUES escritura   · #{issue['number']} · {issue['html_url']}")
        await engine.close_task(issue["number"])
        print(f"✅ ISSUES cierre      · #{issue['number']} cerrado")
    except httpx.HTTPStatusError as e:
        msg = e.response.json().get("message", "")
        print(f"❌ ISSUES · HTTP {e.response.status_code}: {msg}")
        print("   → El PAT de dispatch necesita el permiso 'Issues: Read and write'.")
    finally:
        await engine.aclose()

    # ── Drive ────────────────────────────────────────────────────────────
    google = GoogleClient(
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
        root_folder_id=os.environ["GDRIVE_ROOT_FOLDER_ID"],
    )
    try:
        docs = await google.ensure_folder("documentos")
        print(f"✅ DRIVE carpeta      · 'documentos' ({docs[:12]}...)")
        f = await google.upload("_conexion.md", b"# ok\n", mime="text/markdown", folder_id=docs)
        print(f"✅ DRIVE subida       · {f.name}")
        listing = await google.list_folder(docs)
        print(f"✅ DRIVE listado      · {[x.name for x in listing]}")
        await google.delete(f.id)
        print("✅ DRIVE borrado      · archivo de prueba eliminado")
    except httpx.HTTPStatusError as e:
        print(f"❌ DRIVE · HTTP {e.response.status_code}: {e.response.text[:120]}")
    finally:
        await google.aclose()


if __name__ == "__main__":
    asyncio.run(main())
