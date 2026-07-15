import { useEffect, useState } from "react";
import { FileRow, driveIdFromLink, fetchFileBlob } from "../lib/api";

// Visor en el dashboard: PDF nativo del navegador, CSV en tabla, texto/imagen.
export function FileViewer({ file, onClose }: { file: FileRow; onClose: () => void }) {
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [blobUrl, setBlobUrl] = useState("");
  const [text, setText] = useState("");

  const driveId = file.drive_id || driveIdFromLink(file.drive_link);
  const isPdf = file.mime === "application/pdf";
  const isCsv = file.mime.includes("csv") || file.filename.endsWith(".csv");
  const isText = file.mime.startsWith("text/") || file.mime.startsWith("message/")
    || !!file.filename.match(/\.(txt|md|json|eml)$/);
  const isImage = file.mime.startsWith("image/");

  useEffect(() => {
    if (!driveId) { setState("error"); return; }
    let url = "";
    (async () => {
      try {
        const blob = await fetchFileBlob(driveId);
        if (isCsv || isText) {
          setText(await blob.text());
        } else {
          url = URL.createObjectURL(blob);
          setBlobUrl(url);
        }
        setState("ready");
      } catch {
        setState("error");
      }
    })();
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [driveId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">{file.filename}</div>
            <div className="hashbar" style={{ marginTop: 6, marginBottom: 0 }}>
              <span className="hashlabel">SHA-256</span><code>{file.sha256}</code>
            </div>
          </div>
          <span className="link-btn" onClick={onClose} style={{ fontSize: 18 }}>✕</span>
        </div>
        <div className="modal-body">
          {state === "loading" && <div className="empty">Cargando archivo…</div>}
          {state === "error" && (
            <div className="empty" style={{ color: "var(--rose)" }}>
              No se pudo abrir. {file.drive_link &&
                <a href={file.drive_link} target="_blank" rel="noreferrer">Abrir en Drive</a>}
            </div>
          )}
          {state === "ready" && isPdf && (
            <iframe title={file.filename} src={blobUrl} style={{ width: "100%", height: "100%", border: 0 }} />
          )}
          {state === "ready" && isImage && (
            <img src={blobUrl} alt={file.filename} style={{ maxWidth: "100%" }} />
          )}
          {state === "ready" && isCsv && <CsvTable text={text} />}
          {state === "ready" && isText && !isCsv && <pre className="viewer-text">{text}</pre>}
        </div>
      </div>
    </div>
  );
}

function CsvTable({ text }: { text: string }) {
  const rows = text.split(/\r?\n/).filter((r) => r.trim()).slice(0, 500).map((r) => r.split(","));
  if (!rows.length) return <div className="empty">CSV vacío.</div>;
  const [head, ...body] = rows;
  return (
    <table className="grid">
      <thead><tr>{head.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
      <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
}
