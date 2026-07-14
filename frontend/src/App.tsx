import { useEffect, useState } from "react";
import { clearToken, getToken, setToken } from "./lib/api";
import { clearCache } from "./lib/useCached";
import { signInWithDashboardToken } from "./lib/firebase";
import { useDoc } from "./lib/useFirestore";
import { Timeline } from "./views/Timeline";
import { Vault } from "./views/Vault";
import { Files } from "./views/Files";
import { Calendar } from "./views/Calendar";
import { Personas } from "./views/Personas";

interface StatusDoc {
  agent_core: string; honeypot: string; trigger: string; at: string;
}

type View = "vault" | "files" | "personas" | "calendar";

const VIEWS: { id: View; label: string }[] = [
  { id: "vault", label: "Bóveda" },
  { id: "files", label: "Archivos" },
  { id: "personas", label: "Personas" },
  { id: "calendar", label: "Calendario" },
];

function Login({ onOk }: { onOk: () => void }) {
  const [value, setValue] = useState("");
  const [err, setErr] = useState("");

  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const token = value.trim();
    setToken(token);
    try {
      await signInWithDashboardToken(token); // valida y abre sesión Firebase
      onOk();
    } catch {
      clearToken();
      setErr("Token rechazado.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form onSubmit={submit}>
        <h1>documenter agent</h1>
        <div className="tag">ACCESO POR TOKEN</div>
        <input type="password" placeholder="DASHBOARD_API_TOKEN" value={value}
               onChange={(e) => setValue(e.target.value)} autoFocus />
        <button type="submit" disabled={busy}>{busy ? "CONECTANDO…" : "ENTRAR"}</button>
        {err && <div className="err">{err}</div>}
      </form>
    </div>
  );
}

function Hud({ onLogout }: { onLogout: () => void }) {
  const [clock, setClock] = useState("");
  const status = useDoc<StatusDoc>("status/current"); // en vivo desde Firestore
  useEffect(() => {
    const t = setInterval(() => setClock(new Date().toISOString().slice(11, 19)), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="hud">
      <div>
        <h1>✦ documenter agent</h1>
        <div className="sub">SECRETARIO Y DOCUMENTADOR · U2</div>
      </div>
      <div className="stat">
        <div className="row">
          <span><span className="dot on" />núcleo {status?.agent_core || "…"}</span>
          <span><span className="dot armed" />guardián {status?.honeypot || "…"}</span>
        </div>
        <div className="row">
          <span>{status ? `último latido · ${status.trigger} · ${status.at.slice(11, 16)}` : ""}</span>
          <span style={{ fontFamily: "var(--mono)" }}>{clock} UTC</span>
          <span className="link-btn" onClick={onLogout}>salir</span>
        </div>
      </div>
    </div>
  );
}

function logout() {
  clearCache();
  Object.keys(localStorage).filter((k) => k.startsWith("fs:")).forEach((k) => localStorage.removeItem(k));
  clearToken();
}

export function App() {
  const [authed, setAuthed] = useState(false);
  const [booting, setBooting] = useState(!!getToken());
  const [view, setView] = useState<View>("vault");

  // Al recargar, se reestablece la sesión Firebase con el token guardado.
  useEffect(() => {
    const token = getToken();
    if (!token) { setBooting(false); return; }
    signInWithDashboardToken(token)
      .then(() => setAuthed(true))
      .catch(() => clearToken())
      .finally(() => setBooting(false));
  }, []);

  if (booting) return <div className="login"><div className="empty">Conectando…</div></div>;
  if (!authed) return <Login onOk={() => setAuthed(true)} />;

  return (
    <div className="app">
      <Hud onLogout={() => { logout(); setAuthed(false); }} />
      <div className="nav">
        {VIEWS.map((v) => (
          <button key={v.id} className={view === v.id ? "active" : ""} onClick={() => setView(v.id)}>
            {v.label}
          </button>
        ))}
      </div>
      <div className="workspace">
        <div className="main">
          {view === "vault" && <Vault />}
          {view === "files" && <Files />}
          {view === "personas" && <Personas />}
          {view === "calendar" && <Calendar />}
        </div>
        <aside className="rail"><Timeline /></aside>
      </div>
    </div>
  );
}
