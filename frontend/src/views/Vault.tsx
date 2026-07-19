import { useEffect, useMemo, useState } from "react";
import { api, VaultEntry } from "../lib/api";
import { useCached } from "../lib/useCached";
import { Graph, GraphNode, GraphLink } from "../components/Graph";
import { NoteView } from "./NoteView";

// Caché de notas ya leídas (contenido + hash) para la sesión: abrir una nota es instantáneo.
const noteCache = new Map<string, { content: string; hash: string }>();

// /notes es el bloc del agente: lo que escribe por el shell cuando Nico se lo dicta.
// Si falta aquí, el agente escribe y nadie lo ve nunca.
const ROOTS = ["system", "inbox", "documents", "notes", "heartbeat", "timeline"];

type Tree = Record<string, VaultEntry[]>;

function buildGraph(acc: Tree): { nodes: GraphNode[]; links: GraphLink[] } {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  Object.entries(acc).forEach(([root, files], gi) => {
    nodes.push({ id: root, group: gi, kind: "root" });
    files.forEach((f) => {
      const label = f.name.replace(/\.(md|json)$/, "");
      const ext = f.name.match(/\.(md|json)$/)?.[1];
      nodes.push({ id: label, group: gi, kind: "file", root, ext });
      links.push({ source: root, target: label });
    });
  });
  return { nodes, links };
}

async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function Vault() {
  const [content, setContent] = useState("");
  const [raw, setRaw] = useState("");        // contenido crudo del archivo (para editar)
  const [active, setActive] = useState("");
  const [hash, setHash] = useState("");
  const [tab, setTab] = useState<"graph" | "editor">("graph");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState("");

  // Editable: archivos de texto que se muestran como nota (no los tableros heartbeat/timeline).
  const fileRoot = active.split("/")[0];
  const canEdit = active.includes("/") && /\.(md|json)$/.test(active)
    && !["heartbeat", "timeline"].includes(fileRoot);

  // Sin polling: el árbol se lee una vez (revalida solo al reentrar a la vista).
  const { data: tree } = useCached<Tree>("vault:tree", async () => {
    const acc: Tree = {};
    for (const root of ROOTS) {
      try {
        const r = await api.vault(root);
        if (r.type === "folder") acc[root] = r.entries.filter((e) => e.type === "file");
      } catch { /* carpeta vacía */ }
    }
    return acc;
  });

  // El grafo solo se reconstruye si el contenido del árbol cambia (no en cada render).
  const graph = useMemo(() => buildGraph(tree || {}), [JSON.stringify(tree)]);

  // Precarga agresiva: al abrir la Bóveda se leen TODAS las notas y se precalcula su
  // hash en paralelo, así al hacer clic el contenido y el SHA-256 ya están listos.
  useEffect(() => {
    if (!tree) return;
    const paths = ROOTS.flatMap((r) => (tree[r] || []).map((f) => f.path));
    paths.forEach(async (p) => {
      if (noteCache.has(p)) return;
      try {
        const r = await api.vault(p);
        if (r.type === "file") noteCache.set(p, { content: r.content, hash: await sha256(r.content) });
      } catch { /* nota ilegible: se reintenta al abrirla */ }
    });
  }, [JSON.stringify(tree)]);

  function show(path: string, text: string, h: string) {
    setRaw(text);
    setContent(path.endsWith(".json") ? "```json\n" + text + "\n```" : text);
    setHash(h);
  }

  async function open(path: string) {
    setActive(path);
    setTab("editor");
    setEditing(false);
    const cached = noteCache.get(path);
    if (cached) { show(path, cached.content, cached.hash); return; } // instantáneo
    setHash("");
    try {
      const r = await api.vault(path);
      if (r.type === "file") {
        const h = await sha256(r.content);
        noteCache.set(path, { content: r.content, hash: h });
        show(path, r.content, h);
      }
    } catch {
      setContent("_No se pudo leer la nota._");
    }
  }

  // Clic en una carpeta raíz → vista especial de esa carpeta (sin archivo activo).
  function openFolder(root: string) {
    setActive(root);
    setTab("editor");
    setContent("");
    setRaw("");
    setHash("");
    setEditing(false);
  }

  function startEdit() { setDraft(raw); setSaveErr(""); setEditing(true); }

  async function save() {
    setSaving(true);
    setSaveErr("");
    try {
      await api.writeVault(active, draft);
      const h = await sha256(draft);
      noteCache.set(active, { content: draft, hash: h });
      show(active, draft, h);
      setEditing(false);
    } catch {
      setSaveErr("No se pudo guardar (¿gateway actualizado?).");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid2">
      <div className="panel">
        <div className="panel-header"><span className="accent">Bóveda</span></div>
        <div className="panel-body">
          <ul className="tree">
            {ROOTS.map((root) => (
              <li key={root}>
                <div className={`dir ${active === root ? "active" : ""}`}
                     onClick={() => openFolder(root)}>▸ /{root}</div>
                <ul className="tree">
                  {(tree?.[root] || []).map((f) => (
                    <li key={f.path} className={`file ${active === f.path ? "active" : ""}`}
                        onClick={() => open(f.path)}>
                      ▪ {f.name}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header" style={{ gap: 18 }}>
          <span className="subtab" onClick={() => setTab("graph")}
                style={{ color: tab === "graph" ? "var(--cyan)" : "var(--muted)" }}>✦ Constelación</span>
          <span className="subtab" onClick={() => setTab("editor")}
                style={{ color: tab === "editor" ? "var(--cyan)" : "var(--muted)" }}>◫ Nota</span>
          {tab === "editor" && canEdit && (
            <span style={{ marginLeft: "auto", display: "flex", gap: 14, alignItems: "center" }}>
              {saveErr && <span className="err" style={{ fontSize: 11 }}>{saveErr}</span>}
              {editing ? (
                <>
                  <span className="link-btn" onClick={saving ? undefined : save}>
                    {saving ? "guardando…" : "guardar"}</span>
                  <span className="subtab" style={{ color: "var(--muted)" }}
                        onClick={() => setEditing(false)}>cancelar</span>
                </>
              ) : (
                <span className="link-btn" onClick={startEdit}>✎ editar</span>
              )}
            </span>
          )}
        </div>
        <div className="panel-body">
          {tab === "graph" ? (
            <div style={{ height: "100%" }}>
              {graph.nodes.length ? <Graph nodes={graph.nodes} links={graph.links} />
                : <div className="empty">Bóveda vacía.</div>}
            </div>
          ) : active ? (
            <div className="note-wrap">
              {hash && !editing && (
                <div className="hashbar">
                  <span className="hashlabel">SHA-256</span>
                  <code>{hash}</code>
                </div>
              )}
              {editing
                ? <textarea className="note-editor" value={draft}
                            onChange={(e) => setDraft(e.target.value)} spellCheck={false} autoFocus />
                : <NoteView active={active} content={content} tree={tree || {}} onOpen={open} />}
            </div>
          ) : (
            <div className="empty">Elige una nota o carpeta del árbol.</div>
          )}
        </div>
      </div>
    </div>
  );
}
