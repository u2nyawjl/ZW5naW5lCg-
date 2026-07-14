import { useEffect, useState } from "react";
import { api, clearToken, getToken, setToken, StatusResp } from "./lib/api";
import { Timeline } from "./views/Timeline";
import { Vault } from "./views/Vault";
import { Files } from "./views/Files";
import { Calendar } from "./views/Calendar";

type View = "timeline" | "vault" | "files" | "calendar";

const VIEWS: { id: View; label: string }[] = [
  { id: "timeline", label: "Timeline" },
  { id: "vault", label: "Bóveda" },
  { id: "files", label: "Archivos" },
  { id: "calendar", label: "Calendario" },
];

function Login({ onOk }: { onOk: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setToken(value.trim());
    try {
      await api.status();
      onOk();
    } catch {
      clearToken();
      setErr("Token rechazado.");
    }
  }

  return (
    <div className="login">
      <form onSubmit={submit}>
        <h1>U2NyaWJl</h1>
        <p style={{ color: "#7a8a7a", textAlign: "center", fontSize: 11 }}>
          COMMAND CENTER · acceso por token
        </p>
        <input type="password" placeholder="DASHBOARD_API_TOKEN" value={value}
               onChange={(e) => setValue(e.target.value)} autoFocus />
        <button type="submit">ENTRAR</button>
        {err && <div className="err">{err}</div>}
      </form>
    </div>
  );
}

function Hud({ status, onLogout }: { status: StatusResp | null; onLogout: () => void }) {
  const [clock, setClock] = useState("");
  useEffect(() => {
    const t = setInterval(() => setClock(new Date().toISOString().slice(11, 19)), 1000);
    return () => clearInterval(t);
  }, []);

  const hb = status?.last_heartbeat;
  return (
    <div className="hud">
      <div>
        <h1>✦ U2NyaWJl</h1>
        <div className="sub">SECRETARIO Y DOCUMENTADOR · NEXUS</div>
      </div>
      <div className="stat">
        <div className="row">
          <span><span className="dot on" />núcleo {status?.agent_core || "…"}</span>
          <span><span className="dot armed" />guardián {status?.honeypot || "…"}</span>
        </div>
        <div className="row">
          <span>{hb ? `último latido · ${hb.trigger} · ${hb.conclusion} · ${hb.at.slice(11, 16)}` : ""}</span>
          <span style={{ fontFamily: "var(--mono)" }}>{clock} UTC</span>
          <span className="link-btn" onClick={onLogout}>salir</span>
        </div>
      </div>
    </div>
  );
}

export function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [view, setView] = useState<View>("timeline");
  const [status, setStatus] = useState<StatusResp | null>(null);

  useEffect(() => {
    if (!authed) return;
    const load = () => api.status().then(setStatus).catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [authed]);

  if (!authed) return <Login onOk={() => setAuthed(true)} />;

  return (
    <div className="app">
      <Hud status={status} onLogout={() => { clearToken(); setAuthed(false); }} />
      <div className="nav">
        {VIEWS.map((v) => (
          <button key={v.id} className={view === v.id ? "active" : ""} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <div className="main">
        {view === "timeline" && <Timeline />}
        {view === "vault" && <Vault />}
        {view === "files" && <Files />}
        {view === "calendar" && <Calendar />}
      </div>
    </div>
  );
}
