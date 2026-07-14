import { useState } from "react";
import { FileRow } from "../lib/api";
import { useDoc } from "../lib/useFirestore";
import { FileViewer } from "../components/FileViewer";

function vtBadge(status: string): string {
  if (status === "malicious" || status === "suspicious") return "bad";
  if (status === "harmless") return "ok";
  return "warn"; // unknown / skipped / error
}

function decisionBadge(d: string): string {
  return d === "allow" ? "ok" : d === "block" ? "bad" : "warn";
}

export function Files() {
  // files/current es un documento con la lista completa del manifiesto.
  const doc = useDoc<{ items: FileRow[] }>("files/current");
  const rows = doc?.items || [];
  const loading = doc === null;
  const [open, setOpen] = useState<FileRow | null>(null);

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
                  <td>
                    {f.drive_link
                      ? <span className="link-btn" onClick={() => setOpen(f)}>{f.filename}</span>
                      : f.filename}
                  </td>
                  <td style={{ color: "var(--muted)" }}>{f.mime}</td>
                  <td><span className={`badge ${vtBadge(f.vt_status)}`}>{f.vt_status} {f.vt_detections}</span></td>
                  <td><span className={`badge ${decisionBadge(f.decision)}`}>{f.decision}</span></td>
                  <td style={{ color: "var(--faint)" }}>{f.sha256.slice(0, 12)}…</td>
                  <td>{f.drive_link && <span className="link-btn" onClick={() => setOpen(f)}>ver</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {open && <FileViewer file={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
