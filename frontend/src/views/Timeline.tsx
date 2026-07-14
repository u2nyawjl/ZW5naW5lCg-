import { useEffect, useState } from "react";
import { api, LogEvent } from "../lib/api";

// Íconos por naturaleza del evento, como en el mock (emoji para no depender de FontAwesome).
const ICONS: Record<string, string> = {
  heartbeat: "🫀", "email.saved": "📨", "email.discarded": "🗑️",
  "file.scanned": "🛡️", "file.blocked": "⛔", "reminder.sent": "⏰",
  "reminder.error": "⚠️", "honeypot": "🎯", default: "▪",
};

function icon(type: string): string {
  if (ICONS[type]) return ICONS[type];
  const prefix = type.split(".")[0];
  return ICONS[prefix] || ICONS.default;
}

export function Timeline() {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [tl, runs] = await Promise.all([api.timeline(), api.logs()]);
        const merged = [...tl, ...runs.events]
          .sort((a, b) => (a.ts < b.ts ? 1 : -1))
          .slice(0, 100);
        if (alive) setEvents(merged);
      } finally {
        if (alive) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 15000); // refresco tipo "live"
    return () => { alive = false; clearInterval(id); };
  }, []);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="accent">Bitácora de eventos</span>
        <span className="live"><span className="dot on" />EN VIVO</span>
      </div>
      <div className="panel-body">
        {loading && <div className="empty">Cargando…</div>}
        {!loading && events.length === 0 && <div className="empty">Sin eventos aún.</div>}
        {events.map((e, i) => (
          <div key={i} className={`log ${e.level}`}>
            <span className="t">[{e.ts.slice(11, 19)}]</span>
            <span className="ico">{icon(e.type)}</span>
            <span className="msg">
              {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.message}</a> : e.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
