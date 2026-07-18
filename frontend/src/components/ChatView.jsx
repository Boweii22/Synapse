import { useRef, useState } from "react";
import { sendChat } from "../api";

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
            <p>Say something to Synapse. It remembers across sessions -- close this tab, come back tomorrow,</p>
            <p>it'll still recall what you told it, and it'll gracefully forget what stopped mattering.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              <div className="bubble-text">{m.content}</div>
              {m.role === "assistant" && m.recalledMemories?.length > 0 && (
                <details className="recalled-memories">
                  <summary>{m.recalledMemories.length} memories recalled</summary>
                  <ul>
                    {m.recalledMemories.map((mem) => (
                      <li key={mem.id}>
                        <span className={`type-chip ${mem.memory_type}`}>{mem.memory_type}</span> {mem.content}
                        <span className="salience-inline"> (salience {mem.salience.toFixed(2)})</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </div>
        ))}
        {sending && (
          <div className="bubble-row assistant">
            <div className="bubble assistant typing">thinking...</div>
          </div>
        )}
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
        <button type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
