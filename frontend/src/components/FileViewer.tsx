import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, FileRow, driveIdFromLink, fetchFileBlob } from "../lib/api";

// Al abrir un archivo no siempre se quiere lo mismo: a veces el documento, a
// veces qué dijo VirusTotal, a veces solo el resumen. Son cuatro vistas sobre lo
// mismo, y cada una se carga solo si se pide.
type Tab = "visor" | "resumen" | "texto" | "seguridad";

const TABS: [Tab, string][] = [
  ["visor", "📄 Documento"],
  ["resumen", "✦ Resumen"],
  ["texto", "🔤 Texto extraído"],
  ["seguridad", "🛡️ VirusTotal"],
];

function ext(name: string): string {
  return name.split(".").pop()?.toLowerCase() || "";
}

/** Trocea la nota de la bóveda en sus secciones para no re-descargar nada. */
function seccion(nota: string, titulo: string): string {
  const re = new RegExp(`^## ${titulo}\\s*$([\\s\\S]*?)(?=^## |\\Z)`, "m");
  return (re.exec(nota)?.[1] || "").trim();
}

export function FileViewer({ file, onClose }: { file: FileRow; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("visor");
  const [nota, setNota] = useState<string | null>(null);

  // La nota trae el resumen y el texto extraído: una sola lectura para dos pestañas.
  useEffect(() => {
    if (!file.note_path) { setNota(""); return; }
    let alive = true;
    api.vault(file.note_path)
      .then((r) => alive && setNota(r.type === "file" ? r.content : ""))
      .catch(() => alive && setNota(""));
    return () => { alive = false; };
  }, [file.note_path]);

  const resumen = useMemo(
    () => (nota ? seccion(nota, "Resumen") : ""), [nota]);
  const extraido = useMemo(
    () => (nota ? seccion(nota, "Contenido extraído") : ""), [nota]);

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

        <div className="viewer-tabs">
          {TABS.map(([id, label]) => (
            <span key={id} className={`viewer-tab ${tab === id ? "on" : ""}`}
                  onClick={() => setTab(id)}>{label}</span>
          ))}
          {file.drive_link && (
            <a className="viewer-tab ext" href={file.drive_link} target="_blank" rel="noreferrer">
              ↗ Drive
            </a>
          )}
        </div>

        <div className="modal-body">
          {tab === "visor" && <Documento file={file} extraido={extraido} />}

          {tab === "resumen" && (
            nota === null ? <div className="empty">Leyendo la nota…</div>
              : resumen ? <div className="markdown paper"><ReactMarkdown remarkPlugins={[remarkGfm]}>{resumen}</ReactMarkdown></div>
                : <div className="empty">
                    Todavía sin resumen. Se genera cuando el agente procesa el archivo;
                    los subidos antes de esta versión no lo tienen.
                  </div>
          )}

          {tab === "texto" && (
            nota === null ? <div className="empty">Leyendo la nota…</div>
              : extraido ? <pre className="viewer-text">{extraido}</pre>
                : <div className="empty">Sin texto extraído para este archivo.</div>
          )}

          {tab === "seguridad" && <Seguridad file={file} />}
        </div>
      </div>
    </div>
  );
}

// ── pestaña «Documento»: el archivo de verdad ─────────────────────────────

function Documento({ file, extraido }: { file: FileRow; extraido: string }) {
  const [estado, setEstado] = useState<"cargando" | "listo" | "error">("cargando");
  const [blobUrl, setBlobUrl] = useState("");
  const [texto, setTexto] = useState("");
  const [html, setHtml] = useState("");
  const [filas, setFilas] = useState<string[][]>([]);
  const [motivo, setMotivo] = useState("");

  const e = ext(file.filename);
  const driveId = file.drive_id || driveIdFromLink(file.drive_link);
  const esPdf = file.mime === "application/pdf" || e === "pdf";
  const esImagen = file.mime.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"].includes(e);
  const esDocx = e === "docx";
  const esHoja = ["xlsx", "xls", "ods", "csv", "tsv"].includes(e);
  const esTexto = file.mime.startsWith("text/") || file.mime.startsWith("message/")
    || ["txt", "md", "json", "eml", "log"].includes(e);
  // No hay renderizador de pptx en el navegador que valga la pena: para eso está
  // el texto que ya extrajo Unstructured, que es lo que de verdad se quiere leer.
  const esPptx = ["pptx", "ppt", "odp"].includes(e);

  useEffect(() => {
    if (esPptx) { setEstado("listo"); return; }
    if (!driveId) { setMotivo("Este archivo no está en Drive."); setEstado("error"); return; }
    let url = "";
    let alive = true;
    (async () => {
      try {
        const blob = await fetchFileBlob(driveId);
        if (esDocx) {
          const [{ default: mammoth }, buf] = await Promise.all([
            import("mammoth/mammoth.browser"), blob.arrayBuffer(),
          ]);
          const out = await mammoth.convertToHtml({ arrayBuffer: buf });
          if (alive) setHtml(out.value);
        } else if (esHoja) {
          const [XLSX, buf] = await Promise.all([import("xlsx"), blob.arrayBuffer()]);
          const wb = XLSX.read(buf, { type: "array" });
          const hoja = wb.Sheets[wb.SheetNames[0]];
          if (alive) setFilas(XLSX.utils.sheet_to_json(hoja, { header: 1, raw: false }) as string[][]);
        } else if (esTexto) {
          if (alive) setTexto(await blob.text());
        } else {
          url = URL.createObjectURL(blob);
          if (alive) setBlobUrl(url);
        }
        if (alive) setEstado("listo");
      } catch (err: any) {
        if (alive) { setMotivo(String(err?.message || err)); setEstado("error"); }
      }
    })();
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [driveId, esDocx, esHoja, esTexto, esPptx]);

  if (estado === "cargando") return <div className="empty">Abriendo el archivo…</div>;

  if (estado === "error") {
    return (
      <div className="empty">
        No se pudo abrir aquí{motivo && `: ${motivo}`}.
        {file.drive_link && <> <a href={file.drive_link} target="_blank" rel="noreferrer">Abrir en Drive</a></>}
      </div>
    );
  }

  if (esPptx) {
    return (
      <>
        <div className="viewer-nota">
          Las presentaciones no se dibujan en el navegador. Esto es su contenido,
          diapositiva a diapositiva, tal como lo extrajo el agente.
        </div>
        {extraido ? <pre className="viewer-text">{extraido}</pre>
          : <div className="empty">Sin texto extraído.</div>}
      </>
    );
  }
  if (esPdf) return <iframe title={file.filename} src={blobUrl} className="viewer-frame" />;
  if (esImagen) return <img src={blobUrl} alt={file.filename} className="viewer-img" />;
  if (esDocx) return <div className="markdown paper" dangerouslySetInnerHTML={{ __html: html }} />;
  if (esHoja) return <Hoja filas={filas} />;
  if (esTexto) return <pre className="viewer-text">{texto}</pre>;

  return (
    <div className="empty">
      Sin visor para «.{e}».
      {file.drive_link && <> <a href={file.drive_link} target="_blank" rel="noreferrer">Abrir en Drive</a></>}
    </div>
  );
}

function Hoja({ filas }: { filas: string[][] }) {
  if (!filas.length) return <div className="empty">Hoja vacía.</div>;
  const [cab, ...cuerpo] = filas;
  return (
    <div style={{ overflow: "auto" }}>
      <table className="grid">
        <thead><tr>{cab.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>
        <tbody>
          {cuerpo.slice(0, 500).map((r, i) => (
            <tr key={i}>{cab.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {cuerpo.length > 500 && (
        <div className="viewer-nota">Mostrando 500 de {cuerpo.length} filas.</div>
      )}
    </div>
  );
}

// ── pestaña «VirusTotal» ──────────────────────────────────────────────────

function Seguridad({ file }: { file: FileRow }) {
  const malo = file.vt_status === "malicious" || file.vt_status === "suspicious";
  const explica: Record<string, string> = {
    harmless: "Ningún motor lo marca. Verificado.",
    malicious: "Motores antivirus lo marcan como malicioso. No se subió a Drive.",
    suspicious: "Algún motor lo considera sospechoso. No se subió a Drive.",
    unknown: "VirusTotal nunca había visto este archivo. Es lo NORMAL en un documento "
      + "privado tuyo: solo significa que nadie más lo ha subido nunca.",
    skipped: "No se consultó (sin clave de API configurada).",
    error: "VirusTotal no pudo responder (cuota o red). Se reintenta en cada latido.",
  };
  return (
    <div className="vt-panel">
      <div className={`vt-verdict ${malo ? "bad" : file.vt_status === "harmless" ? "ok" : "warn"}`}>
        <div className="vt-big">{file.vt_detections || "—"}</div>
        <div className="vt-sub">motores lo marcan</div>
      </div>
      <dl className="vt-list">
        <dt>Estado</dt><dd>{file.vt_status}</dd>
        <dt>Decisión</dt><dd>{file.decision}</dd>
        <dt>Tipo real</dt><dd>{file.mime}</dd>
        <dt>SHA-256</dt><dd><code style={{ wordBreak: "break-all" }}>{file.sha256}</code></dd>
        {file.ingested_at && <><dt>Analizado</dt><dd>{file.ingested_at.slice(0, 16).replace("T", " ")}</dd></>}
      </dl>
      <div className="viewer-nota">{explica[file.vt_status] || ""}</div>
      <a className="link-btn" target="_blank" rel="noreferrer"
         href={`https://www.virustotal.com/gui/file/${file.sha256}`}>
        Ver el informe completo en VirusTotal ↗
      </a>
    </div>
  );
}
