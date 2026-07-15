import { useEffect, useRef, useState } from "react";
import { ChatMsg, Conversation, chat, compileLatex, convAction, listModels } from "../lib/api";
import { useCollection } from "../lib/useFirestore";
import { plantumlUrl } from "../lib/plantuml";

function LatexBlock({ code }: { code: string }) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  async function open() {
    setState("busy");
    try {
      window.open(URL.createObjectURL(await compileLatex(code)), "_blank");
      setState("idle");
    } catch { setState("error"); }
  }
  return (
    <div className="latex">
      <div className="latex-head">
        <span>📄 Reporte LaTeX</span>
        <button onClick={open} disabled={state === "busy"}>
          {state === "busy" ? "compilando…" : state === "error" ? "reintentar" : "ver PDF"}
        </button>
      </div>
      <pre>{code.trim()}</pre>
    </div>
  );
}

function MessageContent({ content }: { content: string }) {
  const re = /```(plantuml|puml|latex|tex)\s*([\s\S]*?)```/g;
  const out: React.ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) out.push(<span key={k++}>{content.slice(last, m.index)}</span>);
    const lang = m[1], code = m[2];
    if (lang === "latex" || lang === "tex") out.push(<LatexBlock key={k++} code={code} />);
    else out.push(<img key={k++} className="uml" src={plantumlUrl(code)} alt="diagrama PlantUML"
                       onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />);
    last = m.index + m[0].length;
  }
  if (last < content.length) out.push(<span key={k++}>{content.slice(last)}</span>);
  return <>{out}</>;
}

export function Chat() {
  const conversations = useCollection<Conversation>("conversations", "updated", 50);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listModels().then((r) => { setModels(r.models); setModel(r.default); }).catch(() => {});
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  function openConv(c: Conversation) {
    setActiveId(c.id);
    setMessages(c.messages || []);
  }
  function newConv() { setActiveId(null); setMessages([]); }

  async function remove(c: Conversation, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(`¿Borrar «${c.title}»?`)) return;
    try { await convAction("delete", c.id); } catch { /* ignora */ }
    if (activeId === c.id) newConv();
  }

  async function rename(c: Conversation, e: React.MouseEvent) {
    e.stopPropagation();
    const t = prompt("Nuevo nombre:", c.title);
    if (t && t.trim()) { try { await convAction("rename", c.id, t.trim()); } catch { /* ignora */ } }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    const next: ChatMsg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const r = await chat(next, model || undefined, activeId || undefined);
      setActiveId(r.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: r.reply }]);
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "⚠️ No pude responder ahora mismo." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-wrap">
      <aside className="conv-list">
        <button className="conv-new" onClick={newConv}>＋ Nueva conversación</button>
        {conversations.map((c) => (
          <div key={c.id} className={`conv-item ${activeId === c.id ? "active" : ""}`} onClick={() => openConv(c)}>
            <span className="conv-title">{c.title}</span>
            <span className="conv-actions">
              <span onClick={(e) => rename(c, e)} title="Renombrar">✎</span>
              <span onClick={(e) => remove(c, e)} title="Borrar">🗑</span>
            </span>
          </div>
        ))}
      </aside>

      <div className="panel chat-main">
        <div className="panel-header">
          <span className="accent">Chat con U2</span>
          {models.length > 0 && (
            <select className="model-select" value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
        </div>
        <div className="panel-body chat-body">
          {messages.length === 0 && (
            <div className="empty">Escríbele a U2. Ej: «¿qué tengo esta semana?», «diagrama del flujo de un correo».</div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role}`}><MessageContent content={m.content} /></div>
          ))}
          {busy && <div className="bubble assistant typing">U2 está pensando…</div>}
          <div ref={endRef} />
        </div>
        <form className="chat-input" onSubmit={send}>
          <input value={input} onChange={(e) => setInput(e.target.value)}
                 placeholder="Escribe un mensaje…" autoFocus />
          <button type="submit" disabled={busy || !input.trim()}>Enviar</button>
        </form>
      </div>
    </div>
  );
}
