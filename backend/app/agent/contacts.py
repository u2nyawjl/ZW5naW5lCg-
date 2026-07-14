"""Extracción de personas de un correo (determinista, sin LLM).

Un correo —sobre todo uno reenviado— lleva a mucha gente en las cabeceras y, cuando es
un *forward*, en el bloque citado del cuerpo ("Para: A <a@x>, B <b@y>, …"). Los sacamos
todos por regex: es completo y gratis, no gasta tokens del cerebro.

El correo es DATO: aquí solo se leen direcciones, nunca se obedece nada de su contenido.
"""

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Nombre opcional inmediatamente antes de <correo> (formato "NOMBRE <correo>").
NAME_EMAIL_RE = re.compile(
    r"([A-Za-zÀ-ÿ][\wÀ-ÿ .'\-]{0,58}?)?\s*<\s*"
    r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*>"
)

# Buzones automáticos: no son personas a documentar.
_AUTO = ("no-reply", "noreply", "no_reply", "donotreply", "do-not-reply", "notifications",
         "notification", "mailer", "mailer-daemon", "postmaster", "bounce", "bounces",
         "support", "alerts", "alert", "newsletter", "updates", "automated", "root")

_HEADER_WORDS = ("para", "de ", "cc", "to", "from", "asunto", "fecha", "date", "subject")


def _role(email_addr: str) -> str | None:
    """Rol inferido del dominio; None si es un buzón automático (se ignora)."""
    local, _, dom = email_addr.lower().partition("@")
    if any(a in local for a in _AUTO):
        return None
    if dom.endswith("alumnos.ucn.cl"):
        return "companero"
    if dom.endswith("ucn.cl"):
        return "coordinacion"
    return "externo"


def _pretty(name: str, email_addr: str) -> str:
    """Nombre legible: usa el del correo si lo hay; si no, lo deriva de la parte local."""
    name = (name or "").strip(" \t\r\n\"'<>,;")
    if name and "@" not in name and not name.lower().startswith(_HEADER_WORDS):
        return name.title() if name.isupper() else name
    local = re.sub(r"\d+", "", email_addr.split("@")[0])
    parts = [p for p in re.split(r"[._\-]+", local) if p]
    return " ".join(p.capitalize() for p in parts) or email_addr


def extract_people(msg, own_address: str = "") -> list[dict]:
    """Devuelve [{email, name, role}] únicos, sin buzones automáticos ni el propio agente."""
    own = (own_address or "").strip().lower()
    out: dict[str, dict] = {}

    def add(name: str, email_addr: str) -> None:
        email_addr = (email_addr or "").strip().lower()
        if not EMAIL_RE.fullmatch(email_addr) or email_addr == own:
            return
        role = _role(email_addr)
        if role is None:
            return
        pretty = _pretty(name, email_addr)
        cur = out.get(email_addr)
        if cur is None:
            out[email_addr] = {"email": email_addr, "name": pretty, "role": role}
        elif " " in pretty and " " not in cur["name"]:
            cur["name"] = pretty  # prefiere un nombre real sobre uno derivado

    add(getattr(msg, "from_name", ""), msg.sender)
    for nm, em in getattr(msg, "recipients", []):
        add(nm, em)

    norm = re.sub(r"\s+", " ", msg.body or "")
    paired: set[str] = set()
    for m in NAME_EMAIL_RE.finditer(norm):
        add(m.group(1) or "", m.group(2))
        paired.add(m.group(2).lower())
    for em in EMAIL_RE.findall(norm):
        if em.lower() not in paired:
            add("", em)

    return list(out.values())
