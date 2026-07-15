import { useEffect, useRef, useState } from "react";
import { ChatMsg, chat } from "../lib/api";

export function Chat() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

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
      const reply = await chat(next);
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
        <span style={{ color: "var(--faint)", fontSize: 11 }}>con tu agenda y tareas en vivo</span>
      </div>
      <div className="panel-body chat-body">
        {messages.length === 0 && (
          <div className="empty">Escríbele a U2. Ej: «¿qué tengo esta semana?», «resume mis tareas».</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>{m.content}</div>
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
