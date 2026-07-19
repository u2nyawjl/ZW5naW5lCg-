import { useEffect, useState } from "react";
import { API_BASE, clearToken, getToken, isDegraded, setDegraded, setToken } from "./lib/api";
import { clearCache } from "./lib/useCached";
import { signInWithDashboardToken } from "./lib/firebase";
import { useDoc } from "./lib/useFirestore";
import { Timeline } from "./views/Timeline";
import { Vault } from "./views/Vault";
import { Files } from "./views/Files";
import { Calendar } from "./views/Calendar";
import { Personas } from "./views/Personas";
import { Chat } from "./views/Chat";
import { Usage } from "./views/Usage";

interface StatusDoc {
  agent_core: string; honeypot: string; trigger: string; at: string;
}

type View = "chat" | "vault" | "files" | "personas" | "calendar" | "usage";

const VIEWS: { id: View; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "vault", label: "Bóveda" },
  { id: "files", label: "Archivos" },
  { id: "personas", label: "Personas" },
  { id: "calendar", label: "Calendario" },
  { id: "usage", label: "Uso" },
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
      // Quien manda es el gateway: si acepta el token, se entra. Firebase solo
      // añade las vistas en vivo. Atar el acceso a Firebase dejaba a Nico fuera
      // de SUS PROPIOS datos —que están en GitHub, no en Firestore— el día que
      // Google tumbó la service account (2026-07-19).
      const r = await fetch(`${API_BASE}/api/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) throw new Error("token");
      try {
        await signInWithDashboardToken(token);
      } catch {
        setDegraded();   // se entra igual, sin las vistas en vivo
      }
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
  const [view, setView] = useState<View>(() => {
    const h = window.location.hash.replace(/^#\/?/, "");   // soporta .../#/chat
    return (VIEWS.some((v) => v.id === h) ? h : "vault") as View;
  });
  useEffect(() => { window.location.hash = `/${view}`; }, [view]);

  // Al recargar, se reestablece la sesión Firebase con el token guardado.
  useEffect(() => {
    const token = getToken();
    if (!token) { setBooting(false); return; }
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/status`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!r.ok) throw new Error("token");
        // Firebase es opcional: si no responde, se entra en modo degradado.
        try { await signInWithDashboardToken(token); } catch { setDegraded(); }
        setAuthed(true);
      } catch {
        clearToken();
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  if (booting) return <div className="login"><div className="empty">Conectando…</div></div>;
  if (!authed) return <Login onOk={() => setAuthed(true)} />;

  const degradado = isDegraded();

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
      {degradado && (
        <div className="degraded">
          Firebase no responde: las vistas en vivo (bitácora, personas, uso) muestran
          lo último guardado. La bóveda, los archivos y el chat vienen de GitHub y
          funcionan con normalidad.
        </div>
      )}
      <div className="workspace">
        <div className="main">
          {view === "chat" && <Chat />}
          {view === "vault" && <Vault />}
          {view === "files" && <Files />}
          {view === "personas" && <Personas />}
          {view === "calendar" && <Calendar />}
          {view === "usage" && <Usage />}
        </div>
        <aside className="rail"><Timeline /></aside>
      </div>
    </div>
  );
}
