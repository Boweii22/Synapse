import { useEffect, useState } from "react";
import { createUser } from "./api";
import ChatView from "./components/ChatView";
import MemoryTimeline from "./components/MemoryTimeline";
import "./App.css";

const USER_ID_STORAGE_KEY = "synapse_user_id";

export default function App() {
  const [userId, setUserId] = useState(null);
  const [view, setView] = useState("chat");
  const [error, setError] = useState(null);

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
        <p>Connecting to Synapse...</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-dot" />
          Synapse
        </div>
        <nav className="tabs">
          <button className={view === "chat" ? "tab active" : "tab"} onClick={() => setView("chat")}>
            Chat
          </button>
          <button className={view === "timeline" ? "tab active" : "tab"} onClick={() => setView("timeline")}>
            Memory Timeline
          </button>
        </nav>
        <div className="user-id-badge" title={userId}>
          user: {userId.slice(0, 8)}
        </div>
      </header>

      <main className="app-main">
        {view === "chat" ? <ChatView userId={userId} /> : <MemoryTimeline userId={userId} />}
      </main>
    </div>
  );
}
