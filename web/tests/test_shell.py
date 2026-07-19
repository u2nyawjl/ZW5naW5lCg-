"""Pruebas del shell con una bóveda falsa: sin red, sin GitHub, sin deploy."""

from datetime import timedelta, timezone

import pytest

from _shell import Shell, parse, resolve

TZ = timezone(timedelta(hours=-4))

FILES = {
    "inbox/Inducción Capstone · 9418d2.md": (
        "# Inducción Capstone\n\nLa reunión es el jueves 23/07 a las 11:40.\n"
        "Asisten Evelyn y el coordinador.\n"
    ),
    "inbox/Aviso de seguridad · 2c6320.md": "# Aviso\n\nActualiza laravel.\n",
    "system/mission.md": "# Misión\n\nSecretario y documentador.\n",
    "system/embeddings.json": '{"notes": {"AAAA": "base64basura"}}',
    "mail/cursor.json": '{"uid": 34}',
    "people/directory.json": '{"a@b.cl": {"name": "Evelyn"}}',
}


def _tree(files: dict):
    """Igual que la git trees API: blobs + las carpetas que implican."""
    out, dirs = [], set()
    for p, body in files.items():
        parts = p.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
        out.append({"path": p, "type": "blob", "size": len(body)})
    out += [{"path": d, "type": "tree", "size": 0} for d in dirs]
    return out


def make_shell(**over):
    store = dict(FILES)
    log = []

    async def read(p):
        return store.get(p)

    async def tree():
        return _tree(store)

    async def write(p, c, m):
        store[p] = c
        log.append(("write", p))
        return True

    async def delete(p, m):
        store.pop(p, None)
        log.append(("delete", p))
        return True

    async def search(q, n):
        return [(0.66, "inbox/Inducción Capstone · 9418d2.md", "La reunión es el jueves")]

    async def proc_calendar():
        return "Inducción Capstone · 2026-07-23 11:40"

    kwargs = dict(read=read, tree=tree, write=write, delete=delete, search=search,
                  procs={"calendar": proc_calendar}, tz=TZ)
    kwargs.update(over)
    sh = Shell(**kwargs)
    sh.store, sh.log = store, log
    return sh


# ── parser ───────────────────────────────────────────────────────────────

def test_parse_comillas_y_espacios():
    stages, target, append = parse('cat "inbox/Inducción Capstone · 9418d2.md"')
    assert stages == [["cat", "inbox/Inducción Capstone · 9418d2.md"]]
    assert target == ""


def test_parse_tuberia_y_redireccion():
    stages, target, append = parse('grep -i foo . | head -n 3 >> notes/x.md')
    assert stages == [["grep", "-i", "foo", "."], ["head", "-n", "3"]]
    assert (target, append) == ("notes/x.md", True)


def test_parse_comilla_sin_cerrar():
    with pytest.raises(ValueError):
        parse('cat "sin cerrar')


@pytest.mark.parametrize("raw,want", [
    ("/inbox/x.md", "inbox/x.md"),
    ("./inbox/x.md", "inbox/x.md"),
    ("inbox//x.md", "inbox/x.md"),
    ("../../../etc/passwd", "etc/passwd"),      # el '..' en la raíz se queda en la raíz
    ("inbox/../system/mission.md", "system/mission.md"),
    ("/", ""),
])
def test_resolve_no_escapa(raw, want):
    assert resolve(raw) == want


# ── lectura ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ls_raiz_incluye_proc():
    out = await make_shell().run("ls")
    assert "inbox/" in out and "system/" in out and "proc/" in out


@pytest.mark.asyncio
async def test_cat_archivo():
    out = await make_shell().run('cat "/inbox/Inducción Capstone · 9418d2.md"')
    assert "jueves 23/07" in out


@pytest.mark.asyncio
async def test_cat_proc_es_sintetico():
    out = await make_shell().run("cat /proc/calendar")
    assert "2026-07-23 11:40" in out


@pytest.mark.asyncio
async def test_cat_inexistente():
    assert "no existe" in await make_shell().run("cat /inbox/nada.md")


@pytest.mark.asyncio
async def test_grep_encuentra():
    out = await make_shell().run("grep -n jueves /inbox")
    assert "Inducción Capstone" in out and ":3:" in out


@pytest.mark.asyncio
async def test_grep_sin_resultados_sugiere_search():
    out = await make_shell().run('grep "reunión de inicio" .')
    assert "search reunión de inicio" in out


@pytest.mark.asyncio
async def test_grep_no_mira_el_indice():
    # El índice es base64: si grep lo leyera, saldría basura en cualquier búsqueda.
    out = await make_shell().run("grep -l base64basura .")
    assert "embeddings" not in out


@pytest.mark.asyncio
async def test_tuberia():
    out = await make_shell().run('cat /system/mission.md | grep -c Misión | head -n 1')
    assert out  # no revienta encadenando


@pytest.mark.asyncio
async def test_find_por_nombre():
    out = await make_shell().run("find / -name '*.json'")
    assert "/mail/cursor.json" in out and "/people/directory.json" in out


@pytest.mark.asyncio
async def test_search_semantico():
    out = await make_shell().run("search reunión de inicio del capstone")
    assert "0.66" in out and "Inducción Capstone" in out


@pytest.mark.asyncio
async def test_date_en_hora_de_chile():
    assert "hora de Chile" in await make_shell().run("date")


@pytest.mark.asyncio
async def test_comando_desconocido_lista_los_validos():
    out = await make_shell().run("sudo rm -rf /")
    assert "no existe" in out and "search" in out


# ── escritura y guardas ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redireccion_escribe_en_notes():
    sh = make_shell()
    out = await sh.run('echo "recordar comprar café" > notes/todo.md')
    assert "escrito /notes/todo.md" in out
    assert "café" in sh.store["notes/todo.md"]


@pytest.mark.asyncio
async def test_append_conserva_lo_anterior():
    sh = make_shell()
    await sh.run('echo primero > notes/t.md')
    await sh.run('echo segundo >> notes/t.md')
    assert sh.store["notes/t.md"].split() == ["primero", "segundo"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", [
    'echo x > system/mission.md',      # reescribir su propia misión
    'echo x > mail/cursor.json',       # romper el cursor de correo
    'echo x > timeline/2026-07-16.json',
    'echo x > proc/calendar',
    'echo x > /etc/passwd',
    'echo x > notes/script.sh',        # extensión no permitida
])
async def test_escrituras_prohibidas(cmd):
    sh = make_shell()
    out = await sh.run(cmd)
    assert "solo lectura" in out or "solo se puede escribir" in out or "solo archivos" in out
    assert sh.log == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", [
    'echo x > memory/nucleo.md',
    'echo x >> memory/nucleo.md',
    'rm /memory/nucleo.md',
    'mv /memory/nucleo.md /memory/otro.md',
])
async def test_nucleo_de_memoria_es_intocable(cmd):
    """El núcleo va en TODOS los prompts: quien lo escribe define la conducta del
    agente. Si un correo lograra colar algo ahí, mandaría para siempre."""
    sh = make_shell()
    out = await sh.run(cmd)
    assert "solo lo edita Nico" in out
    assert sh.log == []


@pytest.mark.asyncio
async def test_echo_interpreta_saltos_de_linea():
    """El modelo escribe cabeceras con \\n; si no se interpretan, el recuerdo
    entero queda en una línea y la procedencia deja de ser legible."""
    sh = make_shell()
    await sh.run(r'echo "---\ntipo: proyecto\n---\nRodrigo Alfaro" > memory/g.md')
    assert sh.store["memory/g.md"].splitlines()[:3] == ["---", "tipo: proyecto", "---"]


@pytest.mark.asyncio
async def test_echo_acepta_el_flag_e():
    sh = make_shell()
    await sh.run(r'echo -e "uno\ndos" > notes/e.md')
    assert sh.store["notes/e.md"].splitlines() == ["uno", "dos"]


@pytest.mark.asyncio
async def test_json_invalido_no_se_escribe():
    """Interpretar \\n puede partir una cadena JSON: mejor fallar que corromper."""
    sh = make_shell()
    out = await sh.run(r'echo "{\"a\": \"uno\ndos\"}" > notes/x.json')
    assert "no es JSON válido" in out
    assert "notes/x.json" not in sh.store


@pytest.mark.asyncio
async def test_json_valido_si_se_escribe():
    sh = make_shell()
    out = await sh.run('echo \'{"a": 1}\' > notes/ok.json')
    assert "escrito /notes/ok.json" in out


@pytest.mark.asyncio
async def test_memoria_normal_si_es_escribible():
    sh = make_shell()
    out = await sh.run('echo "entrega movida al 5" > memory/entrega.md')
    assert "escrito /memory/entrega.md" in out
    assert "entrega movida al 5" in sh.store["memory/entrega.md"]


@pytest.mark.asyncio
async def test_rm_recursivo_prohibido():
    sh = make_shell()
    assert "deshabilitados" in await sh.run("rm -rf /inbox")
    assert sh.log == []


@pytest.mark.asyncio
async def test_rm_de_solo_lectura_prohibido():
    sh = make_shell()
    await sh.run("rm /system/mission.md")
    assert sh.log == []
    assert "system/mission.md" in sh.store


@pytest.mark.asyncio
async def test_rm_en_notes_funciona():
    sh = make_shell()
    await sh.run("echo hola > notes/x.md")
    assert "borrado" in await sh.run("rm notes/x.md")
    assert "notes/x.md" not in sh.store


@pytest.mark.asyncio
async def test_mv_renombra():
    sh = make_shell()
    await sh.run("echo hola > notes/a.md")
    out = await sh.run("mv notes/a.md notes/b.md")
    assert "→" in out
    assert "notes/b.md" in sh.store and "notes/a.md" not in sh.store
