import { useEffect, useRef, useState } from "react";
import { createUser } from "./api";
import ChatView from "./components/ChatView";
import MemoryTimeline from "./components/MemoryTimeline";
import "./App.css";

const USER_ID_STORAGE_KEY = "synapse_user_id";
const VIEWS = [
  { key: "chat", label: "Chat" },
  { key: "timeline", label: "Memory Timeline" },
];

export default function App() {
  const [userId, setUserId] = useState(null);
  const [view, setView] = useState("chat");
  const [error, setError] = useState(null);
  const tabRefs = useRef({});
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });

  useEffect(() => {
    const existing = localStorage.getItem(USER_ID_STORAGE_KEY);
    if (existing) {
      setUserId(existing);
      return;
    }
    createUser()
      .then((data) => {
        localStorage.setItem(USER_ID_STORAGE_KEY, data.user_id);
        setUserId(data.user_id);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const el = tabRefs.current[view];
    if (el) setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
  }, [view, userId]);

  if (error) {
    return (
      <div className="app-shell centered">
        <p className="error-text">Couldn't reach the Synapse backend: {error}</p>
        <p className="hint-text">Make sure the FastAPI server is running on the configured API URL.</p>
      </div>
    );
  }

  if (!userId) {
    return (
      <div className="app-shell centered">
        <div className="boot-brand">
          <span className="brand-dot" />
          <span className="boot-text">Connecting to Synapse&hellip;</span>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-dot" />
          <span className="brand-word">Synapse</span>
        </div>
        <nav className="tabs">
          <span className="tab-indicator" style={{ left: indicator.left, width: indicator.width }} />
          {VIEWS.map((v) => (
            <button
              key={v.key}
              ref={(el) => (tabRefs.current[v.key] = el)}
              className={view === v.key ? "tab active" : "tab"}
              onClick={() => setView(v.key)}
            >
              {v.label}
            </button>
          ))}
        </nav>
        <div className="user-id-badge" title={userId}>
          <span className="badge-dot" />
          {userId.slice(0, 8)}
        </div>
      </header>

      <main className="app-main">
        <div key={view} className="view-transition">
          {view === "chat" ? <ChatView userId={userId} /> : <MemoryTimeline userId={userId} />}
        </div>
      </main>
    </div>
  );
}
