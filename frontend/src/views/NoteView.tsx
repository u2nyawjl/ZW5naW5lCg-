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
      <div className="matrix-scan" />
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

// ───────────────────────── heartbeat (monitor de hospital) ────────────────
function ecgPath(): string {
  // Onda PQRST repetida a lo ancho; se desplaza con CSS.
  const seg = "l14,0 l4,-6 l3,14 l4,-40 l4,44 l4,-12 l4,0 l10,0";
  let d = "M0,60 ";
  for (let i = 0; i < 12; i++) d += seg + " ";
  return d;
}
function within(ts: string, since: Date) { return new Date(ts) >= since; }

function HeartbeatMonitor() {
  const events = useCollection<LogEvent>("timeline", "ts", 200);
  const now = new Date();
  const dayAgo = new Date(now.getTime() - 864e5);
  const weekAgo = new Date(now.getTime() - 7 * 864e5);
  const monthAgo = new Date(now.getTime() - 30 * 864e5);

  const tally = (since: Date) => {
    const evs = events.filter((e) => within(e.ts, since));
    return {
      latidos: evs.filter((e) => e.type === "heartbeat").length,
      correos: evs.filter((e) => e.type === "email.saved").length,
      eventos: evs.filter((e) => e.type === "calendar.created").length,
      personas: evs.filter((e) => e.type === "people.added").length,
    };
  };
  const cols: [string, Date][] = [["Hoy", dayAgo], ["Semana", weekAgo], ["Mes", monthAgo]];
  const bpm = 60 + Math.min(40, tally(dayAgo).latidos * 3);

  return (
    <div className="hb">
      <div className="hb-monitor">
        <div className="hb-bpm"><span className="hb-bpm-n">{bpm}</span><span className="hb-bpm-u">BPM</span></div>
        <div className="ecg">
          <svg viewBox="0 0 560 120" preserveAspectRatio="none">
            <path className="ecg-line" d={ecgPath()} />
          </svg>
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
