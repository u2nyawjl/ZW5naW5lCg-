#!/usr/bin/env python3
"""Consigue el refresh token de Google para el agente y prepara su carpeta en Drive.

    python3 scripts/google_oauth.py

Requiere GOOGLE_OAUTH_CLIENT_ID y GOOGLE_OAUTH_CLIENT_SECRET ya puestos en .env
(OAuth client tipo "Desktop app"). Escribe el refresh token y el ID de la carpeta
de vuelta en .env. Solo stdlib: no instala nada.
"""

import http.server
import json
import os
import pathlib
import re
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"

# drive.file: el agente solo ve los archivos que él mismo crea. Es el scope NO sensible,
# sin verificación de Google ni pantallas de advertencia. El precio: no puede leer los
# archivos que subas tú a mano. Los documentos entran por correo, no por Drive.
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/calendar",
]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
ROOT_FOLDER_NAME = "U2NyaWJl"


def read_env() -> dict[str, str]:
    env = {}
    for line in ENV.read_text().splitlines():
        m = re.match(r"^([A-Z_0-9]+)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip()
    return env


def write_env(key: str, value: str) -> None:
    text = ENV.read_text()
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
    else:
        text += f"\n{key}={value}\n"
    ENV.write_text(text)
    os.chmod(ENV, 0o600)


def post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def api(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    env = read_env()
    client_id = env.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = env.get("GOOGLE_OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ Falta GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET en .env")
        print("   Créalos en la consola de Google Cloud (OAuth client → Desktop app).")
        return 1

    port = free_port()
    redirect_uri = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    received: dict[str, str] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            received.update({k: v[0] for k, v in qs.items()})
            ok = received.get("state") == state and "code" in received
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Listo. Vuelve a la terminal." if ok else "Fallo en la autorización."
            self.wfile.write(
                f"<body style='background:#050505;color:#0f0;font-family:monospace;"
                f"display:grid;place-items:center;height:100vh'><h2>U2NyaWJl // {msg}</h2>"
                f"</body>".encode()
            )
            done.set()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",       # sin esto Google NO devuelve refresh token
        "prompt": "consent",            # fuerza uno nuevo aunque ya hubieras autorizado
        "state": state,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("\n  Abriendo el navegador. Inicia sesión con u2nyawjl@gmail.com.")
    print("  Si sale 'Google no ha verificado esta app' → Configuración avanzada → Continuar.")
    print("  Es tu propia app pidiendo acceso a tu propia cuenta.\n")
    print(f"  Si no se abre solo:\n  {url}\n")
    webbrowser.open(url)

    if not done.wait(timeout=300):
        print("❌ Se agotó el tiempo esperando la autorización.")
        return 1
    server.shutdown()

    if received.get("state") != state:
        print("❌ El 'state' no coincide: posible intento de CSRF. Abortado.")
        return 1
    if "code" not in received:
        print(f"❌ Google devolvió: {received.get('error', 'sin código')}")
        return 1

    tokens = post_form(
        TOKEN_URL,
        {
            "code": received["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )

    refresh = tokens.get("refresh_token")
    access = tokens["access_token"]
    if not refresh:
        print("❌ Google no devolvió refresh_token.")
        print("   Suele pasar si la app sigue en modo 'Testing' o ya estaba autorizada.")
        return 1

    write_env("GOOGLE_OAUTH_REFRESH_TOKEN", refresh)
    print(f"✅ Refresh token guardado en .env ({len(refresh)} chars)")

    # Carpeta raíz del agente en Drive. Con drive.file solo ve lo que él crea,
    # así que la busca entre las suyas y si no existe la crea.
    query = urllib.parse.quote(
        f"name='{ROOT_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    found = api(f"{DRIVE_FILES}?q={query}&fields=files(id,name)", access)
    files = found.get("files", [])

    if files:
        folder_id = files[0]["id"]
        print(f"✅ Carpeta '{ROOT_FOLDER_NAME}' ya existía en Drive")
    else:
        folder = api(
            f"{DRIVE_FILES}?fields=id",
            access,
            method="POST",
            payload={"name": ROOT_FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"},
        )
        folder_id = folder["id"]
        print(f"✅ Carpeta '{ROOT_FOLDER_NAME}' creada en Drive")

    write_env("GDRIVE_ROOT_FOLDER_ID", folder_id)
    print(f"   https://drive.google.com/drive/folders/{folder_id}\n")
    print("Listo. El agente ya tiene Drive y Calendar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
