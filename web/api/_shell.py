"""Un shell de Linux sobre la bóveda.

Por qué un shell y no una tool por capacidad: un LLM ha visto millones de sesiones
de terminal y ninguna de `read_note(path=...)`. `ls`, `cat`, `grep` y las tuberías
son la superficie más natural que se le puede dar, componen entre sí, y añadir una
capacidad nueva es añadir un comando —no un schema nuevo, ni un deploy del frontend.

El árbol es la bóveda (un repo de git) más un /proc sintético con lo que no es un
archivo: agenda, tareas, servicios, uso de tokens. Se resuelven bajo demanda, así
que el contexto del chat dejó de pagar por adelantado lo que quizá no se use.

`grep` es literal; `search` es semántico (el índice de embeddings). Cuando grep no
encuentra nada, lo dice y sugiere search: la herramienta enseña a usarse.

Este módulo es puro —sin FastAPI, sin variables de entorno— para poder probarlo sin
desplegar. El gateway le inyecta el acceso real por callbacks.
"""

import base64
import fnmatch
import re
import shlex
from array import array
from datetime import datetime

# Raíces que el chat NO puede modificar:
#   proc       sintético, no existe en disco
#   system     misión, estado e índice. Si el modelo pudiera editar su propia
#              misión, un correo malicioso tendría por dónde reescribirla
#   mail       el cursor de UID: corromperlo = reprocesar o saltarse correo
#   timeline / files / heartbeat   bitácoras que escribe la máquina
READONLY = ("proc", "system", "mail", "timeline", "files", "heartbeat")
WRITABLE = ("inbox", "documents", "notes", "memory")
WRITABLE_EXT = (".md", ".json")

# El núcleo se inyecta en TODOS los prompts, así que quien lo escribe decide cómo
# se comporta el agente para siempre. Eso es de Nico y solo de Nico: se edita desde
# el dashboard. Un recuerdo normal solo se lee si la búsqueda lo trae a cuento;
# el núcleo se lee siempre, y esa diferencia es justo la que hay que proteger.
PROTECTED = ("memory/nucleo.md",)

# El índice es un blob de base64 de cientos de KB: grep -r encontraría basura en él
# y llenaría la respuesta. Se lee con `search`, no con grep.
SKIP_IN_GREP = ("system/embeddings.json",)

MAX_OUT = 8000    # tope de lo que un comando devuelve al modelo
MAX_FILE = 6000   # tope por archivo en `cat`

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def resolve(path: str) -> str:
    """'/inbox/x.md', 'inbox/x.md', './inbox/x.md' → 'inbox/x.md'.

    Un '..' en la raíz se queda en la raíz, igual que en un Linux real (`cd /..`
    es `/`). Por eso no hace falta rechazar el traversal: es imposible expresarlo.
    """
    parts: list[str] = []
    for seg in (path or "").replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def unpack(blob: str) -> array:
    """Desempaqueta un vector float32+base64 del índice. (El backend tiene su
    propia copia: es otro deploy y no puede importar este módulo.)"""
    out = array("f")
    out.frombytes(base64.b64decode(blob))
    return out


def parse(line: str) -> tuple[list[list[str]], str, bool]:
    """`a b | c > d` → ([['a','b'], ['c']], 'd', False)."""
    lex = shlex.shlex(line, posix=True, punctuation_chars="|><")
    lex.whitespace_split = True
    try:
        tokens = list(lex)
    except ValueError as exc:
        raise ValueError(f"no pude leer la línea ({exc}); ¿comilla sin cerrar?") from exc

    stages: list[list[str]] = []
    cur: list[str] = []
    target, append = "", False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "|":
            if not cur:
                raise ValueError("tubería sin comando a la izquierda")
            stages.append(cur)
            cur = []
        elif tok in (">", ">>"):
            if i + 1 >= len(tokens):
                raise ValueError("redirección sin destino")
            target, append = tokens[i + 1], tok == ">>"
            i += 1
        else:
            cur.append(tok)
        i += 1
    if cur:
        stages.append(cur)
    return stages, target, append


def _flags(args: list[str]) -> tuple[set, list[str]]:
    """Separa -abc en {'a','b','c'}. No sirve para opciones con valor (-name X)."""
    flags: set = set()
    rest: list[str] = []
    for a in args:
        if len(a) > 1 and a[0] == "-" and not a[1].isdigit():
            flags.update(a.lstrip("-"))
        else:
            rest.append(a)
    return flags, rest


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (recortado; {len(text) - limit} caracteres más)"


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} K"
    return f"{n / 1048576:.1f} M"


class Shell:
    """Un shell por petición de chat. Cachea árbol y contenidos: el modelo suele
    encadenar varios comandos y no tiene sentido repetir las llamadas a GitHub."""

    def __init__(self, *, read, tree, write, delete, search, procs, tz):
        self._read = read          # async (path) -> str | None
        self._tree = tree          # async () -> [{"path","type","size"}]
        self._write = write        # async (path, content, message) -> bool
        self._delete = delete      # async (path, message) -> bool
        self._search = search      # async (query, limit) -> [(score, path, head)]
        self._procs = procs        # {nombre: async () -> str}
        self._tz = tz
        self._tree_cache: list | None = None
        self._file_cache: dict = {}
        self.commands = {
            n[5:]: getattr(self, n) for n in dir(self) if n.startswith("_cmd_")
        }

    # ── plomería ─────────────────────────────────────────────────────────

    async def _paths(self) -> list:
        if self._tree_cache is None:
            self._tree_cache = await self._tree()
        return self._tree_cache

    def _invalidate(self) -> None:
        self._tree_cache = None
        self._file_cache.clear()

    async def _get(self, path: str) -> str | None:
        if path.startswith("proc/"):
            provider = self._procs.get(path[5:])
            return await provider() if provider else None
        if path in self._file_cache:
            return self._file_cache[path]
        content = await self._read(path)
        self._file_cache[path] = content
        return content

    async def _isdir(self, path: str) -> bool:
        if path in ("", "proc"):
            return True
        return any(e["path"] == path and e["type"] == "tree" for e in await self._paths())

    async def _isfile(self, path: str) -> bool:
        if path.startswith("proc/"):
            return path[5:] in self._procs
        return any(e["path"] == path and e["type"] == "blob" for e in await self._paths())

    async def _listdir(self, prefix: str) -> list | None:
        if prefix == "proc":
            return sorted((n, "blob", 0) for n in self._procs)
        if not await self._isdir(prefix):
            return None
        base = f"{prefix}/" if prefix else ""
        seen: dict = {}
        for e in await self._paths():
            if not e["path"].startswith(base):
                continue
            rest = e["path"][len(base):]
            if not rest or "/" in rest:
                continue
            seen[rest] = (rest, e["type"], e.get("size", 0))
        if prefix == "":
            seen["proc"] = ("proc", "tree", 0)
        return sorted(seen.values())

    async def _expand(self, paths: list[str]) -> list[str]:
        """Rutas → lista de archivos. Una carpeta se expande recursivamente."""
        out: list[str] = []
        for raw in paths:
            p = resolve(raw)
            if await self._isfile(p):
                out.append(p)
                continue
            if await self._isdir(p):
                base = f"{p}/" if p else ""
                out += [
                    e["path"] for e in await self._paths()
                    if e["type"] == "blob"
                    and e["path"].startswith(base)
                    and e["path"] not in SKIP_IN_GREP
                ]
        return out

    def _writable(self, path: str, check_ext: bool = True) -> str:
        """Devuelve '' si se puede escribir ahí; si no, el motivo."""
        if not path:
            return "la raíz no es escribible"
        root = path.split("/")[0]
        if root in READONLY:
            return f"/{root} es de solo lectura"
        if path in PROTECTED:
            return (f"/{path} solo lo edita Nico desde el dashboard: se inyecta en todos "
                    f"tus prompts. Para un recuerdo normal usa /memory/<nombre>.md")
        if root not in WRITABLE:
            return "solo se puede escribir en " + ", ".join("/" + w for w in WRITABLE)
        if check_ext and not path.endswith(WRITABLE_EXT):
            return "solo archivos .md o .json"
        return ""

    # ── ejecución ────────────────────────────────────────────────────────

    async def run(self, line: str) -> str:
        line = (line or "").strip()
        if not line:
            return ""
        try:
            stages, target, append = parse(line)
        except ValueError as exc:
            return f"sh: {exc}"
        if not stages:
            return ""

        out = ""
        for argv in stages:
            out = await self._exec(argv, out)
        if target:
            return await self._redirect(out, target, append)
        return _clip(out, MAX_OUT)

    async def _exec(self, argv: list[str], stdin: str) -> str:
        cmd, args = argv[0], argv[1:]
        fn = self.commands.get(cmd)
        if fn is None:
            return (f"sh: {cmd}: no existe. Comandos: "
                    + ", ".join(sorted(self.commands)))
        try:
            return await fn(args, stdin)
        except Exception as exc:
            return f"{cmd}: {type(exc).__name__}: {exc}"

    async def _redirect(self, content: str, target: str, append: bool) -> str:
        path = resolve(target)
        why = self._writable(path)
        if why:
            return f"sh: {target}: {why}"
        if append:
            current = await self._get(path) or ""
            if current:
                content = current.rstrip("\n") + "\n" + content
        body = content.rstrip("\n") + "\n"
        ok = await self._write(path, body, f"chat: escribe {path}")
        self._invalidate()
        return f"escrito /{path} ({len(body)} bytes)" if ok else f"sh: no se pudo escribir /{path}"

    # ── comandos ─────────────────────────────────────────────────────────

    async def _cmd_help(self, args, stdin):
        return (
            "ls [-l] [ruta]           lista una carpeta\n"
            "cat <ruta...>            muestra un archivo\n"
            "search <consulta>        BÚSQUEDA SEMÁNTICA: encuentra por significado\n"
            "grep [-i|-n|-l] PAT [r]  busca texto literal (regex)\n"
            "find [ruta] -name GLOB   busca por nombre\n"
            "tree [ruta]              árbol\n"
            "head/tail [-n N] [ruta]  primeras/últimas líneas\n"
            "wc [-l] [ruta]           cuenta líneas/palabras/caracteres\n"
            "date                     fecha y hora de Chile\n"
            "echo <texto>             escribe en la salida\n"
            "mkdir <ruta>             crea carpeta\n"
            "rm <ruta>                borra un archivo\n"
            "mv <origen> <destino>    mueve/renombra\n"
            "\nTuberías (|) y redirección (>, >>) funcionan. Las rutas con espacios "
            "van entre comillas.\n"
            f"Escritura solo en: {', '.join('/' + w for w in WRITABLE)} (.md o .json).\n"
            "/proc es sintético y vivo: calendario, tareas, servicios, uso de tokens."
        )

    async def _cmd_ls(self, args, stdin):
        flags, paths = _flags(args)
        targets = paths or [""]
        out: list[str] = []
        for raw in targets:
            p = resolve(raw)
            entries = await self._listdir(p)
            if entries is None:
                if await self._isfile(p):
                    out.append(f"/{p}")
                else:
                    out.append(f"ls: no existe: /{p}")
                continue
            if len(targets) > 1:
                out.append(f"\n/{p}:")
            for name, kind, size in entries:
                if "l" in flags:
                    mark = "d" if kind == "tree" else "-"
                    out.append(f"{mark}  {_size(size):>8}  {name}")
                else:
                    out.append(name + ("/" if kind == "tree" else ""))
        return "\n".join(out)

    async def _cmd_cat(self, args, stdin):
        _, paths = _flags(args)
        if not paths:
            return stdin
        out: list[str] = []
        for raw in paths:
            p = resolve(raw)
            content = await self._get(p)
            if content is None:
                out.append(f"cat: no existe: /{p}")
                continue
            if len(paths) > 1:
                out.append(f"==> /{p} <==")
            out.append(_clip(content, MAX_FILE))
        return "\n".join(out)

    async def _cmd_search(self, args, stdin):
        _, rest = _flags(args)
        query = " ".join(rest).strip() or stdin.strip()
        if not query:
            return "search: uso: search <consulta en lenguaje natural>"
        rows = await self._search(query, 5)
        if rows is None:
            return "search: el índice semántico no está disponible."
        if not rows:
            return f"search: nada parecido a «{query}» en la bóveda."
        out = []
        for score, path, head in rows:
            out.append(f"{score:.2f}  /{path}")
            if head:
                out.append(f"      {head}")
        return "\n".join(out)

    async def _cmd_grep(self, args, stdin):
        flags, rest = _flags(args)
        if not rest:
            return "grep: uso: grep [-i] [-n] [-l] PATRÓN [ruta...]"
        pattern, paths = rest[0], rest[1:]
        try:
            rx = re.compile(pattern, re.IGNORECASE if "i" in flags else 0)
        except re.error as exc:
            return f"grep: patrón inválido: {exc}"

        hits: list[str] = []
        if stdin and not paths:
            for i, line in enumerate(stdin.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{i}:{line}" if "n" in flags else line)
            return "\n".join(hits[:200])

        for p in await self._expand(paths or [""]):
            content = await self._get(p)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if not rx.search(line):
                    continue
                if "l" in flags:
                    hits.append(f"/{p}")
                    break
                loc = f"/{p}:{i}:" if "n" in flags else f"/{p}:"
                hits.append(loc + line.strip()[:200])
        if not hits:
            # El momento en que la herramienta enseña a usarse: el modelo acaba de
            # descubrir que no hay coincidencia LITERAL, que no es lo mismo que
            # que no exista. Sin esta línea concluiría que no hay nada.
            return (f"grep: sin coincidencias literales de «{pattern}».\n"
                    f"grep solo busca texto exacto. Para buscar por significado:  "
                    f"search {pattern}")
        return "\n".join(hits[:200])

    async def _cmd_find(self, args, stdin):
        # -name lleva valor, así que _flags() no sirve aquí.
        start, glob, kind = "", "", ""
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-name" and i + 1 < len(args):
                glob = args[i + 1]
                i += 2
            elif a == "-type" and i + 1 < len(args):
                kind = args[i + 1]
                i += 2
            elif not a.startswith("-"):
                start = a
                i += 1
            else:
                i += 1

        base = resolve(start)
        prefix = f"{base}/" if base else ""
        out: list[str] = []
        for e in await self._paths():
            if not e["path"].startswith(prefix):
                continue
            if kind == "f" and e["type"] != "blob":
                continue
            if kind == "d" and e["type"] != "tree":
                continue
            name = e["path"].rsplit("/", 1)[-1]
            if glob and not (fnmatch.fnmatch(name, glob) or fnmatch.fnmatch(e["path"], glob)):
                continue
            out.append(f"/{e['path']}")
        return "\n".join(sorted(out)) or f"find: sin resultados en /{base}"

    async def _cmd_tree(self, args, stdin):
        _, paths = _flags(args)
        base = resolve(paths[0] if paths else "")
        prefix = f"{base}/" if base else ""
        rows = sorted(
            e["path"] for e in await self._paths() if e["path"].startswith(prefix)
        )
        out = [f"/{base}" if base else "/"]
        for p in rows:
            rest = p[len(prefix):]
            out.append("  " * (rest.count("/") + 1) + rest.rsplit("/", 1)[-1])
        if not base:
            out.append("  proc            (sintético: " + ", ".join(sorted(self._procs)) + ")")
        return "\n".join(out)

    async def _cmd_head(self, args, stdin):
        return await self._headtail(args, stdin, head=True)

    async def _cmd_tail(self, args, stdin):
        return await self._headtail(args, stdin, head=False)

    async def _headtail(self, args, stdin, head: bool):
        n, paths = 10, []
        i = 0
        while i < len(args):
            if args[i] == "-n" and i + 1 < len(args):
                n = int(args[i + 1])
                i += 2
            elif args[i].startswith("-") and args[i][1:].isdigit():
                n = int(args[i][1:])
                i += 1
            else:
                paths.append(args[i])
                i += 1
        if paths:
            content = await self._get(resolve(paths[0]))
            if content is None:
                return f"{'head' if head else 'tail'}: no existe: {paths[0]}"
        else:
            content = stdin
        lines = content.splitlines()
        return "\n".join(lines[:n] if head else lines[-n:])

    async def _cmd_wc(self, args, stdin):
        flags, paths = _flags(args)
        if paths:
            content = await self._get(resolve(paths[0]))
            if content is None:
                return f"wc: no existe: {paths[0]}"
        else:
            content = stdin
        lines = len(content.splitlines())
        if "l" in flags:
            return str(lines)
        return f"{lines} líneas  {len(content.split())} palabras  {len(content)} caracteres"

    async def _cmd_echo(self, args, stdin):
        return " ".join(args)

    async def _cmd_date(self, args, stdin):
        now = datetime.now(self._tz)
        return (f"{_DIAS[now.weekday()]} {now.day} de {_MESES[now.month - 1]} "
                f"de {now.year}, {now:%H:%M} (hora de Chile)")

    async def _cmd_pwd(self, args, stdin):
        return "/"

    async def _cmd_cd(self, args, stdin):
        return "cd: no hace falta; cada comando parte de la raíz. Usa rutas como /inbox/x.md"

    async def _cmd_mkdir(self, args, stdin):
        _, paths = _flags(args)
        if not paths:
            return "mkdir: falta la ruta"
        p = resolve(paths[0])
        why = self._writable(p, check_ext=False)
        if why:
            return f"mkdir: {paths[0]}: {why}"
        # git no guarda carpetas vacías: se crea con un centinela, como haría cualquiera.
        ok = await self._write(f"{p}/.gitkeep", "", f"chat: crea {p}/")
        self._invalidate()
        return f"creada /{p}" if ok else f"mkdir: no se pudo crear /{p}"

    async def _cmd_rm(self, args, stdin):
        flags, paths = _flags(args)
        if flags & {"r", "f"}:
            return "rm: -r y -f están deshabilitados. Borra un archivo a la vez."
        if not paths:
            return "rm: falta la ruta"
        if len(paths) > 1:
            return "rm: un archivo a la vez"
        p = resolve(paths[0])
        why = self._writable(p)
        if why:
            return f"rm: {paths[0]}: {why}"
        if not await self._isfile(p):
            return f"rm: no existe: /{p}"
        ok = await self._delete(p, f"chat: borra {p}")
        self._invalidate()
        return f"borrado /{p}" if ok else f"rm: no se pudo borrar /{p}"

    async def _cmd_mv(self, args, stdin):
        _, paths = _flags(args)
        if len(paths) != 2:
            return "mv: uso: mv <origen> <destino>"
        src, dst = resolve(paths[0]), resolve(paths[1])
        for p, label in ((src, paths[0]), (dst, paths[1])):
            why = self._writable(p)
            if why:
                return f"mv: {label}: {why}"
        content = await self._get(src)
        if content is None:
            return f"mv: no existe: /{src}"
        if not await self._write(dst, content, f"chat: mueve {src} → {dst}"):
            return f"mv: no se pudo escribir /{dst}"
        await self._delete(src, f"chat: mueve {src} → {dst}")
        self._invalidate()
        return f"/{src} → /{dst}"
