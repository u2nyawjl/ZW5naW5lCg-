import { api, FileRow } from "../lib/api";
import { useCached } from "../lib/useCached";

function vtBadge(status: string): string {
  if (status === "malicious" || status === "suspicious") return "bad";
  if (status === "harmless") return "ok";
  return "warn"; // unknown / skipped / error
}

function decisionBadge(d: string): string {
  return d === "allow" ? "ok" : d === "block" ? "bad" : "warn";
}

export function Files() {
  const { data, loading } = useCached<FileRow[]>("files", api.files, 30000);
  const rows = data || [];

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="accent">Archivos</span>
        <span style={{ color: "var(--faint)", fontSize: 11 }}>sistema de archivos del agente</span>
      </div>
      <div className="panel-body">
        {loading && <div className="empty">Cargando…</div>}
        {!loading && rows.length === 0 && <div className="empty">Aún no hay archivos guardados.</div>}
        {rows.length > 0 && (
          <table className="grid">
            <thead>
              <tr><th>Archivo</th><th>Tipo</th><th>VirusTotal</th><th>Decisión</th><th>SHA-256</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.sha256}>
                  <td>{f.filename}</td>
                  <td style={{ color: "#7a8a7a" }}>{f.mime}</td>
                  <td><span className={`badge ${vtBadge(f.vt_status)}`}>{f.vt_status} {f.vt_detections}</span></td>
                  <td><span className={`badge ${decisionBadge(f.decision)}`}>{f.decision}</span></td>
                  <td style={{ color: "#555" }}>{f.sha256.slice(0, 12)}…</td>
                  <td>{f.drive_link && <a href={f.drive_link} target="_blank" rel="noreferrer">Drive</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
