import { useEffect, useMemo, useState } from "react";
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

function hueOf(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}
function initialsOf(name: string): string {
  const p = name.trim().split(/\s+/);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase() || "?";
}

// Avatar: iniciales de color por defecto; intenta Gravatar (los pocos que lo tengan)
// vía hash SHA-256 del correo y cae de vuelta a las iniciales si no existe.
function Avatar({ person }: { person: Person }) {
  const [photo, setPhoto] = useState("");
  useEffect(() => {
    let alive = true;
    crypto.subtle
      .digest("SHA-256", new TextEncoder().encode(person.email.trim().toLowerCase()))
      .then((buf) => {
        const hex = Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
        const url = `https://gravatar.com/avatar/${hex}?s=64&d=404`;
        const img = new Image();
        img.onload = () => { if (alive) setPhoto(url); };
        img.src = url; // d=404 → no dispara onload si no hay foto real
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [person.email]);

  if (photo) return <img className="avatar" src={photo} alt="" />;
  const h = hueOf(person.email);
  return (
    <div className="avatar" style={{ background: `linear-gradient(135deg, hsl(${h} 58% 46%), hsl(${(h + 42) % 360} 58% 34%))` }}>
      {initialsOf(person.name)}
    </div>
  );
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
                  <td>
                    <span className="person-cell">
                      <Avatar person={p} />
                      <span style={{ fontFamily: "var(--sans)", color: "var(--text)" }}>{p.name}</span>
                    </span>
                  </td>
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
