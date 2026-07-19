"""El códec TOON de la bóveda.

Lo que más se prueba aquí son las comas y los dos puntos dentro de un mensaje:
los mensajes de la bitácora son literalmente «Latido (schedule): 0 correos
relevantes, 0 avisos». Si el escapado falla, esa fila se parte en tres y la
bitácora queda corrupta sin que nadie se entere hasta meses después.
"""

import pytest

from app.vault import toon


def test_tabla_declara_columnas_una_vez():
    out = toon.encode({"events": [
        {"ts": "2026-07-19T11:41:40+00:00", "type": "heartbeat", "level": "info"},
        {"ts": "2026-07-19T11:41:38+00:00", "type": "index", "level": "info"},
    ]})
    assert out.splitlines()[0] == "events[2]{ts,type,level}:"
    # El timestamp va entrecomillado porque lleva dos puntos (§7.2). Cuesta dos
    # bytes por fila y es el precio de que un mensaje con «:» nunca parta la fila.
    assert out.splitlines()[1] == '  "2026-07-19T11:41:40+00:00",heartbeat,info'
    # La clave no se repite por fila: solo aparece en la cabecera.
    assert [l for l in out.splitlines() if "ts," in l] == ["events[2]{ts,type,level}:"]


@pytest.mark.parametrize("raw", [
    "Latido (schedule): 0 correos relevantes, 0 avisos",
    'Con "comillas" dentro',
    "Con\\barra invertida",
    "Con\nsalto de línea",
    "coma,al,final,",
    "-empieza con guion",
    "42",                 # parece número: debe volver como cadena
    "true",               # parece booleano
    "",                   # vacío
    "  espacios  ",
])
def test_ida_y_vuelta_de_mensajes_dificiles(raw):
    got = toon.decode(toon.encode({"e": [{"m": raw}]}))["e"][0]["m"]
    assert got == raw


def test_una_coma_no_parte_la_fila():
    txt = toon.encode({"e": [{"a": "uno, dos, tres", "b": "fin"}]})
    fila = toon.decode(txt)["e"][0]
    assert fila == {"a": "uno, dos, tres", "b": "fin"}


def test_tipos_escalares():
    data = {"n": 3, "f": 1.5, "entero_flotante": 2.0, "si": True, "no": False, "nada": None}
    assert toon.decode(toon.encode(data)) == {**data, "entero_flotante": 2}


def test_lista_vacia():
    assert toon.decode(toon.encode({"e": []})) == {"e": []}


def test_cabecera_y_tabla_juntas():
    doc = {"agente": "U2NyaWJl", "desde": "2026-07-14",
           "beats": [{"ts": "2026-07-19T11:41:40+00:00", "correos": 3}]}
    assert toon.decode(toon.encode(doc)) == doc


def test_longitud_mal_declarada_es_error():
    """Un archivo truncado debe explotar, no devolver media bitácora."""
    with pytest.raises(ValueError, match="declara 5"):
        toon.decode("e[5]{a}:\n  1\n  2\n")


def test_fila_con_comilla_sin_cerrar_es_error():
    with pytest.raises(ValueError):
        toon.decode('e[1]{a}:\n  "sin cerrar\n')


def test_columnas_son_la_union_de_todas_las_filas():
    """Los eventos de correo traen `sender`/`category` y los latidos no. Tomar
    las columnas de la primera fila descartaba esos campos EN SILENCIO — solo se
    vio al probar con la bitácora real."""
    filas = [
        {"ts": "1", "type": "heartbeat"},
        {"ts": "2", "type": "email.discarded", "sender": "a@b.com", "category": "ruido"},
    ]
    txt = toon.encode({"e": filas})
    assert txt.splitlines()[0] == "e[2]{ts,type,sender,category}:"
    assert toon.decode(txt)["e"] == filas


def test_ausente_y_vacio_no_son_lo_mismo():
    filas = [{"a": 1}, {"a": 2, "b": ""}]
    vuelta = toon.decode(toon.encode({"e": filas}))["e"]
    assert "b" not in vuelta[0]      # ausente sigue ausente
    assert vuelta[1]["b"] == ""      # vacío sigue vacío
    assert vuelta == filas


def test_mas_barato_que_json():
    """Comparado contra el formato que se usa hoy: json.dumps(indent=2)."""
    import json
    filas = [{"ts": f"2026-07-19T11:{i:02d}:00+00:00", "type": "heartbeat",
              "level": "info", "message": "Latido: 0 relevantes", "meta": ""}
             for i in range(60)]
    t, j = toon.encode({"events": filas}), json.dumps(filas, ensure_ascii=False, indent=2)
    ahorro = 1 - len(t) / len(j)
    assert ahorro > 0.40, f"solo ahorra {ahorro:.0%} (toon={len(t)} json={len(j)})"
