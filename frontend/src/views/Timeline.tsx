import { LogEvent } from "../lib/api";
import { useCollection } from "../lib/useFirestore";

// Íconos por naturaleza del evento, como en el mock (emoji para no depender de FontAwesome).
const ICONS: Record<string, string> = {
  heartbeat: "🫀", "email.saved": "📨", "email.discarded": "🗑️",
  "file.scanned": "🛡️", "file.blocked": "⛔", "reminder.sent": "⏰",
  "reminder.error": "⚠️", "honeypot": "🎯",
  "calendar.created": "📅", "calendar.error": "⚠️", "calendar.duplicate": "📅",
  "email.archived": "🗄️", "people.added": "👥",
  default: "▪",
};

function icon(type: string): string {
  if (ICONS[type]) return ICONS[type];
  const prefix = type.split(".")[0];
  return ICONS[prefix] || ICONS.default;
}

export function Timeline() {
  // En vivo desde Firestore: el heartbeat escribe y esto se actualiza solo.
  const events = useCollection<LogEvent>("timeline", "ts", 100);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="accent">Eventos</span>
        <span className="live"><span className="dot on" />EN VIVO</span>
      </div>
      <div className="panel-body">
        {events.length === 0 && <div className="empty">Esperando el primer latido…</div>}
        <div className="vrail">
          {events.map((e, i) => (
            <div key={i} className={`vrail-item ${e.level}`}>
              <div className="vrail-node">{icon(e.type)}</div>
              <div className="vrail-body">
                <div className="vrail-time">{e.ts.slice(11, 19)}</div>
                <div className="vrail-msg">
                  {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.message}</a> : e.message}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
