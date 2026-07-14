import { useEffect, useState } from "react";
import { api, CalEvent } from "../lib/api";

function fmtDay(iso: string): string {
  return new Date(iso).toLocaleDateString("es-CL", {
    weekday: "long", day: "numeric", month: "long",
  });
}
function fmtTime(ev: CalEvent): string {
  if (ev.all_day) return "todo el día";
  const s = new Date(ev.start), e = new Date(ev.end);
  const t = (d: Date) => d.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  return `${t(s)} – ${t(e)}`;
}

export function Calendar() {
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.calendar()
      .then((r) => setEvents(r.events))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Agrupa por día para una agenda legible.
  const byDay: Record<string, CalEvent[]> = {};
  events.forEach((ev) => {
    const day = ev.start.slice(0, 10);
    (byDay[day] ||= []).push(ev);
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <span>▸ Calendario · Google Calendar del agente</span>
        <span style={{ color: "#7a8a7a" }}>próximos 21 días</span>
      </div>
      <div className="panel-body">
        {loading && <div className="empty">Consultando el calendario…</div>}
        {error && <div className="empty" style={{ color: "#ff003c" }}>Error: {error}</div>}
        {!loading && !error && events.length === 0 && (
          <div className="empty">No hay eventos próximos.</div>
        )}
        {Object.entries(byDay).map(([day, evs]) => (
          <div key={day}>
            <div className="cal-day-label">{fmtDay(day + "T00:00:00")}</div>
            {evs.map((ev) => (
              <a key={ev.id} href={ev.link} target="_blank" rel="noreferrer"
                 style={{ display: "block" }}>
                <div className="cal-event">
                  <div className="when">{fmtTime(ev)}</div>
                  <div className="sum">{ev.summary}</div>
                  {ev.location && <div className="meta">📍 {ev.location}</div>}
                </div>
              </a>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
