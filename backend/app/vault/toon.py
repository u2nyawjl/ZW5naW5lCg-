"""TOON — Token-Oriented Object Notation. https://github.com/toon-format/spec

Por qué, y no JSON: la bitácora es una lista de miles de filas con las MISMAS
claves. En JSON cada fila repite `"ts": …, "type": …, "level": …` — el nombre de
cada campo, en cada evento, para siempre. TOON declara las columnas una sola vez
y luego escribe filas:

    events[2]{ts,type,level,message,meta}:
      2026-07-19T11:41:40+00:00,heartbeat,info,"Latido: 0 relevantes",
      2026-07-19T11:41:38+00:00,index,info,"Índice: 9 notas",

Eso importa porque quien más lee estos archivos es el propio agente, y ahí cada
clave repetida es un token pagado.

Se implementa el SUBCONJUNTO que necesita la bóveda: un objeto raíz con campos
escalares y arrays tabulares de objetos planos. Nada de anidamiento profundo ni
key folding. Lo que sí se respeta al pie de la letra son las reglas de comillas
y escapes (§7), porque de eso depende que un mensaje con comas no parta la fila.
"""

import re

INDENT = "  "

# §7.2 — cuándo una cadena DEBE ir entre comillas.
_NUMERIC = re.compile(r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.I)
_CONTROL = re.compile(r"[\x00-\x1f]")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _needs_quotes(s: str, delim: str = ",") -> bool:
    if s == "" or s != s.strip():
        return True
    if s in ("true", "false", "null") or _NUMERIC.match(s):
        return True
    if s == "-" or s.startswith("-"):
        return True
    if any(c in s for c in (':', '"', "\\", "[", "]", "{", "}", delim)):
        return True
    return bool(_CONTROL.search(s))


def _escape(s: str) -> str:
    out = []
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ch < "\x20":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def _scalar(v, delim: str = ",") -> str:
    """Un valor ya listo para escribir en una celda o tras un `key:`."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        # §2 forma canónica: sin exponente, sin ceros de más, 1.0 → 1
        if isinstance(v, float) and v == int(v) and abs(v) < 1e21:
            return str(int(v))
        return repr(v) if isinstance(v, float) else str(v)
    s = str(v)
    return f'"{_escape(s)}"' if _needs_quotes(s, delim) else s


ABSENT = object()   # celda vacía: el campo no estaba, distinto de estar y ser ""


def _unquote(cell: str) -> object:
    cell = cell.strip()
    if cell == "":
        return ABSENT
    if cell.startswith('"'):
        if not cell.endswith('"') or len(cell) < 2:
            raise ValueError(f"cadena sin cerrar: {cell[:40]}")
        body, out, i = cell[1:-1], [], 0
        while i < len(body):
            if body[i] != "\\":
                out.append(body[i]); i += 1
                continue
            nxt = body[i + 1] if i + 1 < len(body) else ""
            simple = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
            if nxt in simple:
                out.append(simple[nxt]); i += 2
            elif nxt == "u":
                out.append(chr(int(body[i + 2:i + 6], 16))); i += 6
            else:
                raise ValueError(f"escape no válido: \\{nxt}")
        return "".join(out)
    if cell == "null":
        return None
    if cell in ("true", "false"):
        return cell == "true"
    if _NUMERIC.match(cell):
        return float(cell) if ("." in cell or "e" in cell.lower()) else int(cell)
    return cell


def _split_row(line: str, delim: str = ",") -> list[str]:
    """Parte una fila respetando las comillas: un mensaje con comas es UNA celda."""
    cells, cur, quoted, i = [], [], False, 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == "\\" and i + 1 < len(line):
                cur.append(ch); cur.append(line[i + 1]); i += 2; continue
            if ch == '"':
                quoted = False
            cur.append(ch)
        elif ch == '"':
            quoted = True; cur.append(ch)
        elif ch == delim:
            cells.append("".join(cur)); cur = []
        else:
            cur.append(ch)
        i += 1
    if quoted:
        raise ValueError("fila con cadena sin cerrar")
    cells.append("".join(cur))
    return cells


def encode(data: dict) -> str:
    """Objeto raíz → TOON. Las listas de dicts salen como arrays tabulares."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")           # §9.1
                continue
            # La UNIÓN de las claves de todas las filas, no las de la primera: los
            # eventos de correo traen `sender` y `category` que los latidos no, y
            # mirar solo la primera fila los tiraba a la basura sin avisar.
            fields: list[str] = []
            for row in value:
                fields += [k for k in row if k not in fields]
            lines.append(f"{key}[{len(value)}]{{{','.join(fields)}}}:")
            for row in value:
                # Celda vacía = campo ausente. Cadena vacía = `""`. No es lo mismo.
                lines.append(INDENT + ",".join(
                    _scalar(row[f]) if f in row else "" for f in fields))
        else:
            lines.append(f"{key}: {_scalar(value)}")
    return "\n".join(lines) + "\n"


_HEADER = re.compile(r"^(?P<key>[^\[\]{}:]+)\[(?P<n>\d+)\](?:\{(?P<fields>[^}]*)\})?:\s*$")


def decode(text: str) -> dict:
    """TOON → objeto raíz. Verifica que el número de filas sea el declarado."""
    out: dict = {}
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith(" "):            # fila suelta sin cabecera
            raise ValueError(f"línea {i + 1}: fila fuera de una tabla")

        header = _HEADER.match(line)
        if header:
            key = header["key"].strip()
            n = int(header["n"])
            fields = [f.strip() for f in (header["fields"] or "").split(",") if f.strip()]
            rows, i = [], i + 1
            while i < len(lines) and lines[i].startswith(INDENT):
                cells = _split_row(lines[i][len(INDENT):])
                row = {}
                for j, f in enumerate(fields):
                    v = _unquote(cells[j]) if j < len(cells) else ABSENT
                    if v is not ABSENT:
                        row[f] = v
                rows.append(row)
                i += 1
            # La longitud declarada es lo que convierte un archivo truncado en un
            # error en vez de en una bitácora silenciosamente incompleta.
            if len(rows) != n:
                raise ValueError(f"«{key}» declara {n} filas y tiene {len(rows)}")
            out[key] = rows
            continue

        key, _, rest = line.partition(":")
        rest = rest.strip()
        val = [] if rest == "[]" else _unquote(rest)
        out[key.strip()] = "" if val is ABSENT else val
        i += 1
    return out
