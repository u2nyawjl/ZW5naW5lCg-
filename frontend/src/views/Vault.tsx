import { useMemo, useState } from "react";
import { api, VaultEntry } from "../lib/api";
import { useCached } from "../lib/useCached";
import { Graph, GraphNode, GraphLink } from "../components/Graph";
import { NoteView } from "./NoteView";

const ROOTS = ["system", "inbox", "documents", "heartbeat", "timeline"];

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
  const [active, setActive] = useState("");
  const [hash, setHash] = useState("");
  const [tab, setTab] = useState<"graph" | "editor">("graph");

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

  async function open(path: string) {
    setActive(path);
    setTab("editor");
    setHash("");
    try {
      const r = await api.vault(path);
      if (r.type === "file") {
        setContent(path.endsWith(".json") ? "```json\n" + r.content + "\n```" : r.content);
        setHash(await sha256(r.content)); // hash de verificación del .md
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
    setHash("");
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
        </div>
        <div className="panel-body">
          {tab === "graph" ? (
            <div style={{ height: "100%" }}>
              {graph.nodes.length ? <Graph nodes={graph.nodes} links={graph.links} />
                : <div className="empty">Bóveda vacía.</div>}
            </div>
          ) : active ? (
            <div>
              {hash && (
                <div className="hashbar">
                  <span className="hashlabel">SHA-256</span>
                  <code>{hash}</code>
                </div>
              )}
              <NoteView active={active} content={content} tree={tree || {}} onOpen={open} />
            </div>
          ) : (
            <div className="empty">Elige una nota o carpeta del árbol.</div>
          )}
        </div>
      </div>
    </div>
  );
}
