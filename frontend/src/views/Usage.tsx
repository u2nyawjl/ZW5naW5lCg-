import { useEffect, useState } from "react";
import { api, ServiceRow } from "../lib/api";
import { useDoc } from "../lib/useFirestore";

interface UsageDoc {
  prompt_tokens: number; completion_tokens: number; total_tokens: number; calls: number;
  chat_tokens: number; agent_tokens: number; today_tokens: number; today_date: string;
  model: string; updated_at: string;
}

const fmt = (n?: number) => (n ?? 0).toLocaleString("es-CL");

export function Usage() {
  const u = useDoc<UsageDoc>("usage/current");
  const [svc, setSvc] = useState<ServiceRow[]>([]);
  useEffect(() => { api.services().then((r) => setSvc(r.services)).catch(() => {}); }, []);
  const rate = svc.find((s) => s.name === "GitHub API");

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="accent">Uso de tokens</span>
        <span style={{ color: "var(--faint)", fontSize: 11 }}>GitHub Models · agente + chat</span>
      </div>
      <div className="panel-body">
        {u === null && (
          <div className="empty">Aún no hay uso registrado. Se llena con cada latido y cada chat.</div>
        )}
        {u && (
          <>
            <div className="usage-grid">
              <div className="stat-tile"><div className="n">{fmt(u.total_tokens)}</div><div className="l">tokens totales</div></div>
              <div className="stat-tile"><div className="n">{fmt(u.today_tokens)}</div><div className="l">hoy</div></div>
              <div className="stat-tile"><div className="n">{fmt(u.calls)}</div><div className="l">llamadas</div></div>
            </div>
            <table className="grid" style={{ marginTop: 16 }}>
              <tbody>
                <tr><td>Prompt</td><td>{fmt(u.prompt_tokens)}</td></tr>
                <tr><td>Completion</td><td>{fmt(u.completion_tokens)}</td></tr>
                <tr><td>Agente (latidos)</td><td>{fmt(u.agent_tokens)}</td></tr>
                <tr><td>Chat</td><td>{fmt(u.chat_tokens)}</td></tr>
                <tr><td>Modelo por defecto</td><td style={{ fontFamily: "var(--mono)" }}>{u.model}</td></tr>
                {rate && <tr><td>GitHub API (rate)</td><td>{rate.detail}</td></tr>}
                <tr><td>Actualizado</td><td>{(u.updated_at || "").slice(0, 16).replace("T", " ")} UTC</td></tr>
              </tbody>
            </table>
            <div className="usage-note">
              GitHub Models no expone una cuota total, así que se muestra el uso acumulado que
              medimos en cada llamada. Firebase y Meta API se sumarán aquí cuando haya datos.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
