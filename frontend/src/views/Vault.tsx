import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, VaultEntry } from "../lib/api";
import { useCached } from "../lib/useCached";
import { Graph, GraphNode, GraphLink } from "../components/Graph";

// Carpetas raíz de la bóveda que el árbol muestra.
const ROOTS = ["system", "inbox", "documents", "heartbeat", "timeline"];

export function Vault() {
  const [content, setContent] = useState<string>("");
  const [active, setActive] = useState<string>("");
  const [tab, setTab] = useState<"graph" | "editor">("graph");

  // El árbol se cachea: pinta al instante y revalida en segundo plano.
  const { data: tree } = useCached<Record<string, VaultEntry[]>>("vault:tree", async () => {
    const acc: Record<string, VaultEntry[]> = {};
    for (const root of ROOTS) {
      try {
        const r = await api.vault(root);
        if (r.type === "folder") acc[root] = r.entries.filter((e) => e.type === "file");
      } catch { /* carpeta vacía */ }
    }
    return acc;
  }, 30000);

  const graph = buildGraph(tree || {});

  function buildGraph(acc: Record<string, VaultEntry[]>): { nodes: GraphNode[]; links: GraphLink[] } {
    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];
    Object.entries(acc).forEach(([root, files], gi) => {
      nodes.push({ id: root, group: gi });
      files.forEach((f) => {
        const label = f.name.replace(/\.(md|json)$/, "");
        nodes.push({ id: label, group: gi });
        links.push({ source: root, target: label });
      });
    });
    return { nodes, links };
  }

  async function open(path: string) {
    setActive(path);
    setTab("editor");
    try {
      const r = await api.vault(path);
      if (r.type === "file") {
        setContent(path.endsWith(".json") ? "```json\n" + r.content + "\n```" : r.content);
      }
    } catch {
      setContent("_No se pudo leer la nota._");
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
                <div className="dir">▸ /{root}</div>
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
          ) : (
            <div className="markdown">
              {active ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                : <div className="empty">Elige una nota del árbol.</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
