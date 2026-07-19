// TOON — Token-Oriented Object Notation. https://github.com/toon-format/spec
//
// Espejo del códec de Python (backend/app/vault/toon.py). Aquí solo hace falta
// LEER: quien escribe la bóveda es el latido.
//
//   agente: U2NyaWJl
//   beats[3]{ts,trigger,correos}:
//     "2026-07-19T11:41:40Z",schedule,3
//
// La regla que importa: una celda entre comillas puede llevar comas y dos puntos.
// Los mensajes de la bitácora son «Latido (schedule): 0 correos, 0 avisos», así
// que partir por comas a lo bruto rompería una de cada dos filas.

const INDENT = "  ";
const NUMERIC = /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i;
const HEADER = /^([^[\]{}:]+)\[(\d+)\](?:\{([^}]*)\})?:\s*$/;

export type Row = Record<string, string | number | boolean | null>;
export type Doc = Record<string, unknown>;

const ABSENT = Symbol("absent");

function unquote(cell: string): string | number | boolean | null | typeof ABSENT {
  const s = cell.trim();
  if (s === "") return ABSENT;                    // ausente ≠ cadena vacía
  if (s.startsWith('"')) {
    if (!s.endsWith('"') || s.length < 2) throw new Error("cadena sin cerrar");
    const body = s.slice(1, -1);
    let out = "";
    for (let i = 0; i < body.length; i++) {
      if (body[i] !== "\\") { out += body[i]; continue; }
      const n = body[i + 1];
      const simple: Record<string, string> = { "\\": "\\", '"': '"', n: "\n", r: "\r", t: "\t" };
      if (n in simple) { out += simple[n]; i++; }
      else if (n === "u") { out += String.fromCharCode(parseInt(body.slice(i + 2, i + 6), 16)); i += 5; }
      else throw new Error(`escape no válido: \\${n}`);
    }
    return out;
  }
  if (s === "null") return null;
  if (s === "true") return true;
  if (s === "false") return false;
  if (NUMERIC.test(s)) return Number(s);
  return s;
}

function splitRow(line: string): string[] {
  const cells: string[] = [];
  let cur = "", quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === "\\" && i + 1 < line.length) { cur += ch + line[i + 1]; i++; continue; }
      if (ch === '"') quoted = false;
      cur += ch;
    } else if (ch === '"') { quoted = true; cur += ch; }
    else if (ch === ",") { cells.push(cur); cur = ""; }
    else cur += ch;
  }
  if (quoted) throw new Error("fila con cadena sin cerrar");
  cells.push(cur);
  return cells;
}

export function decode(text: string): Doc {
  const out: Doc = {};
  const lines = (text || "").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    const h = HEADER.exec(line);
    if (h) {
      const [, key, n, fieldStr] = h;
      const fields = (fieldStr || "").split(",").map((f) => f.trim()).filter(Boolean);
      const rows: Row[] = [];
      i++;
      while (i < lines.length && lines[i].startsWith(INDENT)) {
        const cells = splitRow(lines[i].slice(INDENT.length));
        const row: Row = {};
        fields.forEach((f, j) => {
          const v = j < cells.length ? unquote(cells[j]) : ABSENT;
          if (v !== ABSENT) row[f] = v as Row[string];
        });
        rows.push(row);
        i++;
      }
      // La longitud declarada convierte un archivo truncado en un error visible,
      // en vez de en un panel que muestra media bitácora como si fuera entera.
      if (rows.length !== Number(n)) {
        throw new Error(`«${key.trim()}» declara ${n} filas y tiene ${rows.length}`);
      }
      out[key.trim()] = rows;
      continue;
    }

    const cut = line.indexOf(":");
    if (cut > 0) {
      const rest = line.slice(cut + 1).trim();
      const v = rest === "[]" ? [] : unquote(rest);
      out[line.slice(0, cut).trim()] = v === ABSENT ? "" : v;
    }
    i++;
  }
  return out;
}
