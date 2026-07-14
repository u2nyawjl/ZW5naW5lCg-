import { useMemo, useState } from "react";
import { Person } from "../lib/api";
import { useDoc } from "../lib/useFirestore";

const ROLE_LABEL: Record<string, string> = {
  companero: "compañero", coordinacion: "coordinación", externo: "externo",
  profesor: "profesor", desconocido: "—",
};

function roleBadge(role: string): string {
  if (role === "coordinacion" || role === "profesor") return "warn";
  if (role === "companero") return "ok";
  return "";
}

export function Personas() {
  const doc = useDoc<{ items: Person[] }>("people/current");
  const all = doc?.items || [];
  const loading = doc === null;
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((p) =>
      p.name.toLowerCase().includes(needle) || p.email.toLowerCase().includes(needle)
    );
  }, [all, q]);

  const byRole = useMemo(() => {
    const c: Record<string, number> = {};
    all.forEach((p) => { c[p.role] = (c[p.role] || 0) + 1; });
    return c;
  }, [all]);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="accent">Personas</span>
        <span style={{ color: "var(--faint)", fontSize: 11 }}>
          {all.length} en el directorio
          {Object.entries(byRole).map(([r, n]) => ` · ${n} ${ROLE_LABEL[r] || r}`)}
        </span>
      </div>
      <div className="panel-body">
        {all.length > 0 && (
          <input className="search" placeholder="Buscar por nombre o correo…"
                 value={q} onChange={(e) => setQ(e.target.value)} />
        )}
        {loading && <div className="empty">Cargando…</div>}
        {!loading && all.length === 0 &&
          <div className="empty">Aún no hay personas. Se llenan con cada correo relevante.</div>}
        {rows.length > 0 && (
          <table className="grid">
            <thead>
              <tr><th>Persona</th><th>Correo</th><th>Rol</th><th>Visto</th></tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.email}>
                  <td style={{ fontFamily: "var(--sans)", color: "var(--text)" }}>{p.name}</td>
                  <td style={{ color: "var(--muted)" }}>{p.email}</td>
                  <td><span className={`badge ${roleBadge(p.role)}`}>{ROLE_LABEL[p.role] || p.role}</span></td>
                  <td style={{ color: "var(--faint)" }}>{(p.last_seen || "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
