import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, VaultEntry } from "../lib/api";
import { useCollection } from "../lib/useFirestore";
import { LogEvent } from "../lib/api";

const ICONS: Record<string, string> = {
  heartbeat: "🫀", "email.saved": "📨", "email.discarded": "🗑️",
  "file.scanned": "🛡️", "file.blocked": "⛔", "reminder.sent": "⏰",
  "reminder.error": "⚠️", "calendar.created": "📅", "calendar.error": "⚠️",
  "people.added": "👥", "honeypot": "🎯", default: "▪",
};
const evIcon = (t: string) => ICONS[t] || ICONS[t.split(".")[0]] || ICONS.default;

// ───────────────────────── inbox / documents (papel claro) ────────────────
function Paper({ content }: { content: string }) {
  return (
    <div className="markdown paper">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

// ───────────────────────── system (matrix azul) ───────────────────────────
function Matrix({ content }: { content: string }) {
  return (
    <div className="markdown matrix">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

// ───────────────────────── timeline (cards desde el json) ──────────────────
function TimelineCards({ json }: { json: string }) {
  const events = useMemo(() => {
    try { const a = JSON.parse(json); return Array.isArray(a) ? (a as LogEvent[]) : []; }
    catch { return []; }
  }, [json]);
  if (!events.length) return <div className="empty">Sin eventos en este archivo.</div>;
  return (
    <div className="tl-cards">
      {events.map((e, i) => (
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
function activityEcg(times: number[]): string {
  const now = Date.now(), start = now - 24 * 3600 * 1000;
  const W = 560, mid = 72, BINS = 56;
  const counts = new Array(BINS).fill(0);
  times.forEach((t) => {
    if (t >= start && t <= now) {
      const b = Math.min(BINS - 1, Math.floor((t - start) / ((now - start) / BINS)));
      counts[b]++;
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

function HeartbeatMonitor() {
  const events = useCollection<LogEvent>("timeline", "ts", 300);
  const now = Date.now();
  const cols: [string, Date][] = [
    ["Hoy", new Date(now - 864e5)], ["Semana", new Date(now - 7 * 864e5)], ["Mes", new Date(now - 30 * 864e5)],
  ];

  // BPM real: mediana del intervalo entre latidos consecutivos.
  const beats = events.filter((e) => e.type === "heartbeat").map((e) => +new Date(e.ts)).sort((a, b) => a - b);
  let medianGap = 0;
  if (beats.length >= 2) {
    const gaps = beats.slice(1).map((t, i) => t - beats[i]).sort((a, b) => a - b);
    medianGap = gaps[Math.floor(gaps.length / 2)];
  }
  const bpm = medianGap > 0 ? 60000 / medianGap : 0;
  const ecg = activityEcg(events.map((e) => +new Date(e.ts)));

  const tally = (since: Date) => {
    const evs = events.filter((e) => new Date(e.ts) >= since);
    return {
      latidos: evs.filter((e) => e.type === "heartbeat").length,
      correos: evs.filter((e) => e.type === "email.saved").length,
      eventos: evs.filter((e) => e.type === "calendar.created").length,
      personas: evs.filter((e) => e.type === "people.added").length,
    };
  };

  return (
    <div className="hb">
      <div className="hb-monitor">
        <div className="hb-bpm">
          <span className="hb-bpm-n">{fmtBpm(bpm)}</span>
          <span className="hb-bpm-u">BPM</span>
          {medianGap > 0 && <span className="hb-bpm-sub">{humanInterval(medianGap)}</span>}
        </div>
        <div className="ecg">
          <svg viewBox="0 0 560 120" preserveAspectRatio="none">
            <path className="ecg-line" d={ecg} />
          </svg>
          <div className="ecg-cursor" />
        </div>
      </div>
      <div className="hb-cols">
        {cols.map(([label, since]) => {
          const t = tally(since);
          return (
            <div key={label} className="hb-col">
              <div className="hb-col-h">{label}</div>
              <div className="hb-stat"><b>{t.latidos}</b> latidos</div>
              <div className="hb-stat"><b>{t.correos}</b> correos</div>
              <div className="hb-stat"><b>{t.eventos}</b> eventos</div>
              <div className="hb-stat"><b>{t.personas}</b> personas</div>
            </div>
          );
        })}
      </div>
      <div className="hb-foot">Actividad real de las últimas 24 h · cada pico es un latido o suceso.</div>
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
    if (root === "timeline") return <FolderTimeline entries={tree.timeline || []} />;
    // system / inbox como carpeta: lista simple para elegir nota.
    return <FolderList entries={tree[root] || []} onOpen={onOpen} />;
  }

  // Vista de archivo, con estilo según la carpeta.
  if (root === "system") return <Matrix content={content} />;
  if (root === "timeline") return <TimelineCards json={content.replace(/^```json\n|\n```$/g, "")} />;
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

function FolderTimeline({ entries }: { entries: VaultEntry[] }) {
  const [json, setJson] = useState("");
  const latest = entries.map((e) => e.path).sort().reverse()[0];
  useEffect(() => {
    if (!latest) return;
    api.vault(latest).then((r) => { if (r.type === "file") setJson(r.content); }).catch(() => {});
  }, [latest]);
  if (!latest) return <div className="empty">Sin bitácora todavía.</div>;
  return <TimelineCards json={json} />;
}
