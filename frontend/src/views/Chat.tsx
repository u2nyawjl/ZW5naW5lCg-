import { useEffect, useRef, useState } from "react";
import { ChatMsg, chat, listModels } from "../lib/api";

// PlantUML se renderiza en cliente con el formato hex (~h): sin librería de deflate.
function plantumlUrl(src: string): string {
  const hex = Array.from(new TextEncoder().encode(src.trim()))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  return `https://www.plantuml.com/plantuml/svg/~h${hex}`;
}

// Divide el texto en fragmentos de texto y bloques ```plantuml, renderizando estos como imagen.
function MessageContent({ content }: { content: string }) {
  const parts = content.split(/```(?:plantuml|puml)\s*([\s\S]*?)```/g);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1
          ? <img key={i} className="uml" src={plantumlUrl(p)} alt="diagrama PlantUML"
                 onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />
          : (p ? <span key={i}>{p}</span> : null)
      )}
    </>
  );
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
