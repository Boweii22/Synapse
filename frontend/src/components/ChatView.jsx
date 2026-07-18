import { useRef, useState } from "react";
import { sendChat } from "../api";

function RecalledMemories({ memories }) {
  const [open, setOpen] = useState(false);
  if (!memories?.length) return null;

  return (
    <div className="recalled-memories">
      <button className="recalled-toggle" onClick={() => setOpen((v) => !v)}>
        <span className={`chevron ${open ? "open" : ""}`}>&#9656;</span>
        {memories.length} {memories.length === 1 ? "memory" : "memories"} recalled
      </button>
      <div className={`recalled-list ${open ? "open" : ""}`}>
        <ul>
          {memories.map((mem) => (
            <li key={mem.id}>
              <span className={`type-chip ${mem.memory_type}`}>{mem.memory_type}</span>
              <span className="recalled-content">{mem.content}</span>
              <span className="salience-inline">{mem.salience.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="bubble-row assistant">
      <div className="bubble assistant typing-bubble">
        <span className="dot" />
        <span className="dot" />
        <span className="dot" />
      </div>
    </div>
  );
}

export default function ChatView({ userId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  const scrollToBottom = () => {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  async function handleSend(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    scrollToBottom();

    try {
      const data = await sendChat(userId, text);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply, recalledMemories: data.recalled_memories },
      ]);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
      scrollToBottom();
    }
  }

  return (
    <div className="chat-view">
      <div className="chat-scroll">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-orb" />
            <p className="empty-title">Say something to Synapse</p>
            <p>It remembers across sessions -- close this tab, come back tomorrow,</p>
            <p>it'll still recall what matters, and gracefully forget what doesn't.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble-row ${m.role}`} style={{ animationDelay: "0ms" }}>
            <div className={`bubble ${m.role}`}>
              <div className="bubble-text">{m.content}</div>
              {m.role === "assistant" && <RecalledMemories memories={m.recalledMemories} />}
            </div>
          </div>
        ))}
        {sending && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <form className="chat-input-row" onSubmit={handleSend}>
        <input
          type="text"
          placeholder="Message Synapse..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button type="submit" className="send-btn" disabled={sending || !input.trim()}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M4 12L20 4L14 20L11 13L4 12Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          </svg>
        </button>
      </form>
    </div>
  );
}
