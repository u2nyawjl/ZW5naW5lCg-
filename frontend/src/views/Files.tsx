import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, FileRow, QueueItem } from "../lib/api";
import { FileViewer } from "../components/FileViewer";

// Icono por extensión, no por MIME: el MIME de un .docx es ilegible y la
// extensión se reconoce de un vistazo.
const ICONS: Record<string, string> = {
  pdf: "📕", doc: "📘", docx: "📘", odt: "📘", rtf: "📘", txt: "📄", md: "📝",
  xls: "📗", xlsx: "📗", ods: "📗", csv: "📊", tsv: "📊",
  ppt: "📙", pptx: "📙", odp: "📙",
  png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", webp: "🖼️", svg: "🖼️", bmp: "🖼️",
  zip: "🗜️", rar: "🗜️", "7z": "🗜️", tar: "🗜️", gz: "🗜️",
  mp3: "🎵", wav: "🎵", ogg: "🎵", flac: "🎵",
  mp4: "🎬", mkv: "🎬", mov: "🎬", avi: "🎬", webm: "🎬",
  json: "🗂️", xml: "🗂️", yml: "🗂️", yaml: "🗂️",
  py: "🐍", js: "📜", ts: "📜", tsx: "📜", html: "🌐", css: "🎨", sql: "🗄️",
  eml: "📨", ics: "📅",
};

function iconFor(name: string, decision: string): string {
  // Un archivo bloqueado se ve como bloqueado, sin importar qué extensión traiga.
  if (decision === "block") return "☣️";
  if (decision === "hold") return "🔒";
  return ICONS[name.split(".").pop()?.toLowerCase() || ""] || "📄";
}

function vtClass(status: string): string {
  if (status === "malicious" || status === "suspicious") return "bad";
  if (status === "harmless") return "ok";
  return "warn";              // unknown / skipped / error
}

function humanSize(n?: number): string {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1_048_576) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1_048_576).toFixed(1)} MB`;
}

const FOLDERS_PATH = "files/folders.json";
const RAIZ = "";

export function Files() {
  const [rows, setRows] = useState<FileRow[] | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [folders, setFolders] = useState<string[]>([]);
  const [cwd, setCwd] = useState(RAIZ);
  const [open, setOpen] = useState<FileRow | null>(null);
  const [dragging, setDragging] = useState(false);
  const [subiendo, setSubiendo] = useState<string[]>([]);
  const [aviso, setAviso] = useState("");
  const [menu, setMenu] = useState<FileRow | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const recargar = useCallback(async () => {
    const [f, q] = await Promise.all([
      api.files().catch(() => [] as FileRow[]),
      api.queue().then((r) => r.queue).catch(() => [] as QueueItem[]),
    ]);
    setRows(f);
    setQueue(q);
    try {
      const r = await api.vault(FOLDERS_PATH);
      if (r.type === "file") setFolders(JSON.parse(r.content));
    } catch { /* aún no hay carpetas creadas */ }
  }, []);

  useEffect(() => { recargar(); }, [recargar]);

  // Mientras haya algo en cola conviene refrescar: el latido lo procesa solo y
  // el panel debe enterarse sin que Nico recargue.
  useEffect(() => {
    if (!queue.length) return;
    const t = setInterval(recargar, 20000);
    return () => clearInterval(t);
  }, [queue.length, recargar]);

  // Las carpetas salen de dos sitios: las creadas a mano y las que ya usa algún
  // archivo. Así una carpeta con contenido nunca desaparece de la lista.
  const todas = useMemo(() => {
    const usadas = (rows || []).map((f) => f.collection || "").filter(Boolean);
    return Array.from(new Set([...folders, ...usadas])).sort();
  }, [folders, rows]);

  const visibles = useMemo(
    () => (rows || []).filter((f) => (f.collection || "") === cwd),
    [rows, cwd],
  );
  const enCola = queue.filter((q) => (q.folder || "") === cwd);

  async function subir(files: FileList | File[]) {
    setAviso("");
    const lista = Array.from(files);
    setSubiendo(lista.map((f) => f.name));
    const fallos: string[] = [];
    for (const f of lista) {
      try {
        await api.upload(f, cwd);
      } catch (e: any) {
        fallos.push(`${f.name}: ${e?.message || e}`);
      }
    }
    setSubiendo([]);
    setAviso(fallos.length
      ? `No se pudo subir — ${fallos.join(" · ")}`
      : `${lista.length} archivo(s) en cola. El agente los escanea y los procesa.`);
    recargar();
  }

  async function mover(f: FileRow, destino: string) {
    setMenu(null);
    try {
      await api.moveFile(f.sha256, destino);
      setAviso(`${f.filename} → /${destino || "documentos"}`);
      recargar();
    } catch {
      setAviso(`No se pudo mover ${f.filename}.`);
    }
  }

  async function nuevaCarpeta() {
    const nombre = prompt("Nombre de la carpeta (p. ej. capstone-2025-2):")?.trim();
    if (!nombre) return;
    const limpio = nombre.replace(/[^A-Za-z0-9 _-]/g, "").trim();
    if (!limpio || todas.includes(limpio)) return;
    const next = [...folders, limpio].sort();
    setFolders(next);
    setCwd(limpio);
    try {
      await api.writeVault(FOLDERS_PATH, JSON.stringify(next, null, 2));
    } catch {
      setAviso("La carpeta se creó en pantalla pero no se pudo guardar.");
    }
  }

  return (
    <div className="panel fm"
         onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
         onDragLeave={() => setDragging(false)}
         onDrop={(e) => {
           e.preventDefault();
           setDragging(false);
           if (e.dataTransfer.files?.length) subir(e.dataTransfer.files);
         }}>
      <div className="panel-header">
        <span className="accent">Archivos</span>
        <span className="fm-path">/{cwd || "documentos"}</span>
        <span className="fm-actions">
          <span className="link-btn" onClick={nuevaCarpeta}>+ carpeta</span>
          <span className="link-btn" onClick={() => input.current?.click()}>⬆ subir</span>
        </span>
      </div>

      <input ref={input} type="file" multiple hidden
             onChange={(e) => e.target.files && subir(e.target.files)} />

      <div className="fm-body">
        <div className="fm-side">
          <div className={`fm-dir ${cwd === RAIZ ? "on" : ""}`} onClick={() => setCwd(RAIZ)}>
            📁 documentos
          </div>
          {todas.map((c) => (
            <div key={c} className={`fm-dir sub ${cwd === c ? "on" : ""}`} onClick={() => setCwd(c)}>
              📂 {c}
            </div>
          ))}
          {todas.length === 0 && <div className="fm-hint">Sin carpetas todavía.</div>}
        </div>

        <div className="fm-main">
          {aviso && <div className="fm-aviso">{aviso}</div>}

          {enCola.length > 0 && (
            <div className="fm-queue">
              <b>{enCola.length}</b> esperando a VirusTotal · el agente reintenta en cada latido
              <div className="fm-queue-list">
                {enCola.map((q) => (
                  <span key={q.sha256} className="fm-chip" title={q.last_error || ""}>
                    ⏳ {q.filename}{q.attempts > 1 ? ` (intento ${q.attempts})` : ""}
                  </span>
                ))}
              </div>
            </div>
          )}

          {subiendo.length > 0 && <div className="fm-queue">Subiendo {subiendo.join(", ")}…</div>}

          {rows === null && <div className="empty">Cargando…</div>}
          {rows !== null && visibles.length === 0 && enCola.length === 0 && (
            <div className="empty fm-drop-hint">
              Arrastra archivos aquí para que el agente los escanee y los archive.
            </div>
          )}

          <div className="fm-grid">
            {visibles.map((f) => (
              <div key={f.sha256} className="fm-item"
                   onClick={() => setOpen(f)}
                   onContextMenu={(ev) => { ev.preventDefault(); setMenu(f); }}
                   title={`${f.filename}\nClic para abrir · clic derecho para mover`}>
                <div className="fm-ico">{iconFor(f.filename, f.decision)}</div>
                <div className="fm-name">{f.filename}</div>
                <div className="fm-meta">
                  <span className={`fm-dot ${vtClass(f.vt_status)}`} />
                  {humanSize(f.size_bytes)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {menu && (
        <div className="fm-menu-backdrop" onClick={() => setMenu(null)}>
          <div className="fm-menu" onClick={(e) => e.stopPropagation()}>
            <div className="fm-menu-h">{menu.filename}</div>
            <div className="fm-menu-i" onClick={() => { setOpen(menu); setMenu(null); }}>Abrir</div>
            <div className="fm-menu-sep">Mover a</div>
            <div className={`fm-menu-i ${!menu.collection ? "on" : ""}`}
                 onClick={() => mover(menu, "")}>📁 documentos</div>
            {todas.map((c) => (
              <div key={c} className={`fm-menu-i ${menu.collection === c ? "on" : ""}`}
                   onClick={() => mover(menu, c)}>📂 {c}</div>
            ))}
          </div>
        </div>
      )}

      {dragging && <div className="fm-overlay">Suelta para subir a /{cwd || "documentos"}</div>}
      {open && <FileViewer file={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
