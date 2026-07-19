import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, VaultEntry, LogEvent, ServiceRow } from "../lib/api";
import { decode as decodeToon, Row } from "../lib/toon";
import { withDiagrams } from "../lib/plantuml";
import { Mermaid } from "../components/Mermaid";

// PlantUML se resuelve antes de renderizar (acaba siendo un <img> a un servidor).
// Mermaid no puede: se dibuja contra el DOM, así que se intercepta el bloque aquí.
const MD_COMPONENTS = {
  code({ className, children, ...props }: any) {
    const lang = /language-(\w+)/.exec(className || "")?.[1];
    if (lang === "mermaid") return <Mermaid code={String(children)} />;
    return <code className={className} {...props}>{children}</code>;
  },
};

const ICONS: Record<string, string> = {
  heartbeat: "🫀", "email.saved": "📨", "email.discarded": "🗑️",
  "file.scanned": "🛡️", "file.blocked": "⛔", "reminder.sent": "⏰",
  "reminder.error": "⚠️", "calendar.created": "📅", "calendar.error": "⚠️",
  "calendar.duplicate": "📅", "email.archived": "🗄️",
  "people.added": "👥", "honeypot": "🎯", default: "▪",
};
const evIcon = (t: string) => ICONS[t] || ICONS[t.split(".")[0]] || ICONS.default;

// ───────────────────────── inbox / documents (papel claro) ────────────────
function Paper({ content }: { content: string }) {
  return (
    <div className="markdown paper">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{withDiagrams(content)}</ReactMarkdown>
    </div>
  );
}

// ───────────────────────── system (matrix azul) ───────────────────────────
function Matrix({ content }: { content: string }) {
  return (
    <div className="markdown matrix">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{withDiagrams(content)}</ReactMarkdown>
    </div>
  );
}

// ───────────────────── timeline (cards desde timeline.dat) ─────────────────
// El archivo trae meses de bitácora; la vista pinta los más recientes y deja
// pedir más, que es más útil que un scroll de seis mil filas.
const TL_PAGE = 120;

function TimelineCards({ toon }: { toon: string }) {
  const [limite, setLimite] = useState(TL_PAGE);
  const { events, error } = useMemo(() => {
    try {
      const rows = (decodeToon(toon).events as unknown as LogEvent[]) || [];
      return { events: rows, error: "" };
    } catch (e: any) {
      return { events: [] as LogEvent[], error: String(e?.message || e) };
    }
  }, [toon]);
  if (error) return <div className="empty">Bitácora ilegible: {error}</div>;
  if (!events.length) return <div className="empty">Sin eventos en la bitácora.</div>;
  return (
    <div className="tl-cards">
      {events.slice(0, limite).map((e, i) => (
        <div key={i} className={`tl-card ${e.level}`}>
          <div className="tl-ico">{evIcon(e.type)}</div>
          <div className="tl-main">
            <div className="tl-top">
              <span className="tl-type">{e.type}</span>
              <span className="tl-time">{e.ts?.slice(11, 19)}</span>
            </div>
            <div className="tl-msg">{e.message}</div>
          </div>
        </div>
      ))}
      {limite < events.length && (
        <div className="tl-more" onClick={() => setLimite((n) => n + TL_PAGE)}>
          ver más ({events.length - limite} eventos anteriores)
        </div>
      )}
    </div>
  );
}

// ───────────────────────── documents (buscador con iconos) ────────────────
const EXT_ICON: Record<string, string> = {
  pdf: "📕", csv: "📊", xlsx: "📗", xls: "📗", pptx: "📙", ppt: "📙",
  doc: "📘", docx: "📘", txt: "📄", md: "📄", json: "🗂️", png: "🖼️", jpg: "🖼️",
};
function DocBrowser({ entries, onOpen }: { entries: VaultEntry[]; onOpen: (p: string) => void }) {
  if (!entries.length) return <div className="empty">Sin documentos guardados todavía.</div>;
  return (
    <div className="doc-grid">
      {entries.map((f) => {
        const name = f.name.replace(/\.md$/, "");
        const ext = (name.match(/\.(\w+)$/)?.[1] || "md").toLowerCase();
        return (
          <div key={f.path} className="doc-item" onDoubleClick={() => onOpen(f.path)}
               onClick={() => onOpen(f.path)} title={name}>
            <div className="doc-ico">{EXT_ICON[ext] || "📄"}</div>
            <div className="doc-name">{name}</div>
          </div>
        );
      })}
    </div>
  );
}

// ───────── heartbeat: monitor con datos REALES ─────────
// El BPM es el ritmo real de latidos (1/día ≈ 0.00069 BPM). El "electro" no es una onda
// cardíaca falsa: es la actividad real de las últimas 24 h (como el gráfico de commits de
// un repo), pero dibujada con forma de ECG para que se vea como un monitor.
function fmtBpm(x: number): string {
  if (x <= 0) return "0";
  if (x >= 1) return Math.round(x).toString();
  return x.toPrecision(2); // p. ej. 0.00069, 0.033
}
function humanInterval(ms: number): string {
  const m = ms / 60000;
  if (m >= 1440) { const d = m / 1440; return `≈ cada ${d >= 10 ? Math.round(d) : d.toFixed(1)} día${d >= 2 ? "s" : ""}`; }
  if (m >= 60) return `≈ cada ${(m / 60).toFixed(1)} h`;
  return `≈ cada ${Math.round(m)} min`;
}
// Cada latido pesa por lo que hizo (correos + eventos + avisos), no por existir:
// una hora en la que llegaron cinco correos debe verse más alta que una vacía.
function activityEcg(points: { t: number; w: number }[], windowMs: number): string {
  const now = Date.now(), start = now - windowMs;
  const W = 560, mid = 72, BINS = 56;
  const counts = new Array(BINS).fill(0);
  points.forEach(({ t, w }) => {
    if (t >= start && t <= now) {
      const b = Math.min(BINS - 1, Math.floor((t - start) / ((now - start) / BINS)));
      counts[b] += Math.max(1, w);
    }
  });
  const max = Math.max(1, ...counts);
  let d = `M0,${mid}`;
  for (let i = 0; i < BINS; i++) {
    const x = ((i + 0.5) / BINS) * W;
    if (counts[i] > 0) {
      const amp = 14 + (counts[i] / max) * 46; // altura del pico ∝ actividad real
      d += ` L${(x - 6).toFixed(1)},${mid} L${(x - 3).toFixed(1)},${(mid + amp * 0.18).toFixed(1)}`
        + ` L${x.toFixed(1)},${(mid - amp).toFixed(1)} L${(x + 3).toFixed(1)},${(mid + amp * 0.28).toFixed(1)}`
        + ` L${(x + 6).toFixed(1)},${mid}`;
    }
  }
  return d + ` L${W},${mid}`;
}

function svcDot(status: string): string {
  return status === "ok" ? "on" : status === "warn" ? "warn" : "down";
}
function ServicesPanel() {
  const [rows, setRows] = useState<ServiceRow[] | null>(null);
  useEffect(() => {
    let alive = true;
    api.services().then((r) => alive && setRows(r.services)).catch(() => alive && setRows([]));
    return () => { alive = false; };
  }, []);
  return (
    <div className="hb-services">
      <div className="hb-col-h">Servicios</div>
      {rows === null && <div className="hb-stat">Comprobando…</div>}
      {rows?.length === 0 && <div className="hb-stat">Sin datos.</div>}
      {rows?.map((s) => (
        <div key={s.name} className="svc">
          <span className={`dot ${svcDot(s.status)}`} />
          <span className="svc-name">{s.name}</span>
          <span className="svc-detail">{s.detail}</span>
        </div>
      ))}
    </div>
  );
}

const RANGOS = [
  ["Día", 24 * 3600e3], ["Semana", 7 * 24 * 3600e3], ["Mes", 30 * 24 * 3600e3],
] as const;

// Lee heartbeat/heart.beat: una fila por latido, formato TOON. Antes esto salía
// de Firestore; ahora la bóveda es la única fuente y el panel muestra justo lo
// que quedó escrito. Se pierde el "en vivo", pero los latidos son horarios.
function HeartbeatMonitor() {
  const [beats, setBeats] = useState<Row[] | null>(null);
  const [err, setErr] = useState("");
  const [rango, setRango] = useState(0);

  useEffect(() => {
    let alive = true;
    api.vault("heartbeat/heart.beat")
      .then((r) => {
        if (!alive) return;
        setBeats(r.type === "file" ? ((decodeToon(r.content).beats as Row[]) || []) : []);
      })
      .catch((e) => alive && setErr(String(e?.message || e)));
    return () => { alive = false; };
  }, []);

  if (err) return <div className="empty">No se pudo leer heart.beat: {err}</div>;
  if (!beats) return <div className="empty">Leyendo constantes vitales…</div>;
  if (!beats.length) return <div className="empty">Todavía no hay latidos registrados.</div>;

  const num = (b: Row, k: string) => Number(b[k] ?? 0);
  const at = (b: Row) => +new Date(String(b.ts));
  const [etiqueta, ventana] = RANGOS[rango];

  // BPM real: mediana del hueco entre latidos consecutivos. Por eso heart.beat
  // guarda una fila por latido y no un total por día.
  const ts = beats.map(at).sort((a, b) => a - b);
  let medianGap = 0;
  if (ts.length >= 2) {
    const gaps = ts.slice(1).map((t, i) => t - ts[i]).sort((a, b) => a - b);
    medianGap = gaps[Math.floor(gaps.length / 2)];
  }
  const bpm = medianGap > 0 ? 60000 / medianGap : 0;

  const ecg = activityEcg(
    beats.map((b) => ({
      t: at(b),
      w: num(b, "correos") + num(b, "eventos") + num(b, "avisos"),
    })),
    ventana,
  );

  const tally = (ms: number) => {
    const desde = Date.now() - ms;
    const en = beats.filter((b) => at(b) >= desde);
    const sum = (k: string) => en.reduce((n, b) => n + num(b, k), 0);
    return {
      latidos: en.length, correos: sum("correos"), relevantes: sum("relevantes"),
      eventos: sum("eventos"), personas: sum("personas"), errores: sum("errores"),
    };
  };

  return (
    <div className="hb">
      <div className="hb-top">
        <div className="hb-bpm">
          <div className="hb-bpm-n">{fmtBpm(bpm)}</div>
          <div className="hb-bpm-u">BPM · {medianGap ? humanInterval(medianGap) : "sin datos"}</div>
        </div>
        <div className="hb-ranges">
          {RANGOS.map(([lab], i) => (
            <span key={lab} className={`hb-range ${i === rango ? "on" : ""}`}
                  onClick={() => setRango(i)}>{lab}</span>
          ))}
        </div>
        <div className="ecg">
          <svg viewBox="0 0 560 120" preserveAspectRatio="none">
            <path className="ecg-line" d={ecg} />
          </svg>
          <div className="ecg-cursor" />
        </div>
      </div>
      <div className="hb-cols">
        {RANGOS.map(([lab, ms]) => {
          const t = tally(ms);
          return (
            <div key={lab} className="hb-col">
              <div className="hb-col-h">{lab}</div>
              <div className="hb-stat"><b>{t.latidos}</b> latidos</div>
              <div className="hb-stat"><b>{t.correos}</b> correos · <b>{t.relevantes}</b> rel.</div>
              <div className="hb-stat"><b>{t.eventos}</b> eventos</div>
              <div className="hb-stat"><b>{t.personas}</b> personas</div>
              {t.errores > 0 && <div className="hb-stat err"><b>{t.errores}</b> fallos</div>}
            </div>
          );
        })}
      </div>
      <ServicesPanel />
      <div className="hb-foot">
        {beats.length} latidos registrados · el electro cubre {etiqueta.toLowerCase()},
        y cada pico vale por lo que hizo ese latido.
      </div>
    </div>
  );
}

// ───────────────────────── router por carpeta ─────────────────────────────
export function NoteView({ active, content, tree, onOpen }: {
  active: string;
  content: string;
  tree: Record<string, VaultEntry[]>;
  onOpen: (path: string) => void;
}) {
  const isFolder = !active.includes("/");
  const root = active.split("/")[0];

  // Vista de carpeta (clic en /documents, /heartbeat, /timeline…).
  if (isFolder) {
    if (root === "documents") return <DocBrowser entries={tree.documents || []} onOpen={onOpen} />;
    if (root === "heartbeat") return <HeartbeatMonitor />;
    if (root === "timeline") return <TimelineFile />;
    // system / inbox como carpeta: lista simple para elegir nota.
    return <FolderList entries={tree[root] || []} onOpen={onOpen} />;
  }

  // Vista de archivo, con estilo según la carpeta.
  if (root === "system") return <Matrix content={content} />;
  if (root === "timeline") return <TimelineCards toon={content} />;
  if (root === "heartbeat") return <HeartbeatMonitor />;
  return <Paper content={content} />; // inbox, documents y por defecto
}

function FolderList({ entries, onOpen }: { entries: VaultEntry[]; onOpen: (p: string) => void }) {
  if (!entries.length) return <div className="empty">Carpeta vacía.</div>;
  return (
    <div className="folder-list">
      {entries.map((f) => (
        <div key={f.path} className="folder-row" onClick={() => onOpen(f.path)}>▪ {f.name}</div>
      ))}
    </div>
  );
}

// Ya no hay que buscar el archivo del día más reciente: la bitácora entera es
// timeline/timeline.dat.
function TimelineFile() {
  const [toon, setToon] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.vault("timeline/timeline.dat")
      .then((r) => alive && setToon(r.type === "file" ? r.content : ""))
      .catch(() => alive && setToon(""));
    return () => { alive = false; };
  }, []);
  if (toon === null) return <div className="empty">Leyendo la bitácora…</div>;
  if (!toon) return <div className="empty">Sin bitácora todavía.</div>;
  return <TimelineCards toon={toon} />;
}
