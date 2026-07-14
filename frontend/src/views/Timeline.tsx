import { LogEvent } from "../lib/api";
import { useCollection } from "../lib/useFirestore";

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
  // En vivo desde Firestore: el heartbeat escribe y esto se actualiza solo.
  const events = useCollection<LogEvent>("timeline", "ts", 100);
  const loading = events.length === 0;

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
