import { useEffect, useRef, useState } from "react";
import { ChatMsg, chat, compileLatex, listModels } from "../lib/api";
import { plantumlUrl } from "../lib/plantuml";

function LatexBlock({ code }: { code: string }) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  async function open() {
    setState("busy");
    try {
      const pdf = await compileLatex(code);
      window.open(URL.createObjectURL(pdf), "_blank");
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

// Trocea el mensaje en texto / diagramas PlantUML / bloques LaTeX.
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

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    const next: ChatMsg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const reply = await chat(next, model || undefined);
      setMessages((m) => [...m, { role: "assistant", content: reply }]);
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: "⚠️ No pude responder ahora mismo." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
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
          <div className="empty">
            Escríbele a U2. Ej: «¿qué tengo esta semana?», «diagrama del flujo de un correo».
          </div>
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
  );
}
