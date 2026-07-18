import { useCallback, useEffect, useState } from "react";
import { listMemories, runConsolidation, runDecay } from "../api";
import BenchmarkChart from "./BenchmarkChart";

const POLL_MS = 5000;

function salienceBarColor(salience) {
  if (salience > 0.6) return "#2563eb";
  if (salience > 0.25) return "#7c9df0";
  return "#c7d2fe";
}

export default function MemoryTimeline({ userId }) {
  const [memories, setMemories] = useState([]);
  const [error, setError] = useState(null);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [jobStatus, setJobStatus] = useState(null);

  const refresh = useCallback(() => {
    listMemories(userId, true)
      .then(setMemories)
      .catch((err) => setError(err.message));
  }, [userId]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const active = memories.filter((m) => m.is_active).sort((a, b) => b.salience - a.salience);
  const recentlyChanged = memories
    .filter((m) => !m.is_active)
    .sort((a, b) => new Date(b.pruned_at) - new Date(a.pruned_at))
    .slice(0, 20);

  async function handleRunDecay() {
    setJobStatus("running decay job...");
    try {
      const res = await runDecay(userId);
      setJobStatus(`decay job: recomputed ${res.detail.recomputed}, pruned ${res.detail.pruned}`);
      refresh();
    } catch (err) {
      setJobStatus(`decay job failed: ${err.message}`);
    }
  }

  async function handleRunConsolidation() {
    setJobStatus("running consolidation pass...");
    try {
      const res = await runConsolidation(userId);
      setJobStatus(`consolidation: merged ${res.detail.consolidated_count} clusters, retired ${res.detail.retired_count} superseded`);
      refresh();
    } catch (err) {
      setJobStatus(`consolidation failed: ${err.message}`);
    }
  }

  return (
    <div className="timeline-view">
      <div className="timeline-toolbar">
        <button onClick={refresh}>Refresh</button>
        <button onClick={handleRunDecay}>Run decay job</button>
        <button onClick={handleRunConsolidation}>Run consolidation pass</button>
        <button className={showBenchmark ? "toggle active" : "toggle"} onClick={() => setShowBenchmark((v) => !v)}>
          {showBenchmark ? "Hide benchmark chart" : "Show benchmark chart"}
        </button>
      </div>

      {jobStatus && <div className="job-status">{jobStatus}</div>}
      {error && <div className="error-banner">{error}</div>}

      {showBenchmark && <BenchmarkChart />}

      <div className="timeline-columns">
        <section className="timeline-column">
          <h3>Active memories ({active.length})</h3>
          <div className="memory-list">
            {active.map((m) => (
              <div key={m.id} className="memory-card">
                <div className="memory-card-header">
                  <span className={`type-chip ${m.memory_type}`}>{m.memory_type}</span>
                  <span className="salience-label">salience {m.salience.toFixed(3)}</span>
                </div>
                <p className="memory-content">{m.content}</p>
                <div className="salience-bar-track">
                  <div
                    className="salience-bar-fill"
                    style={{ width: `${Math.min(100, m.salience * 100)}%`, background: salienceBarColor(m.salience) }}
                  />
                </div>
                <div className="memory-meta">
                  importance {m.importance_score.toFixed(2)} - recalled {m.recall_count}x - last recalled{" "}
                  {new Date(m.last_recalled_at).toLocaleString()}
                </div>
              </div>
            ))}
            {active.length === 0 && <p className="empty-state">No active memories yet -- chat with Synapse first.</p>}
          </div>
        </section>

        <section className="timeline-column">
          <h3>Recently decayed / pruned / consolidated</h3>
          <div className="memory-list">
            {recentlyChanged.map((m) => (
              <div key={m.id} className="memory-card faded">
                <div className="memory-card-header">
                  <span className={`type-chip ${m.memory_type}`}>{m.memory_type}</span>
                  <span className={`pruned-chip ${m.pruned_reason}`}>{m.pruned_reason}</span>
                </div>
                <p className="memory-content">{m.content}</p>
                <div className="memory-meta">
                  {m.pruned_at && `pruned ${new Date(m.pruned_at).toLocaleString()}`}
                  {m.source_memory_ids?.length > 0 && ` - merged from ${m.source_memory_ids.length} memories`}
                </div>
              </div>
            ))}
            {recentlyChanged.length === 0 && (
              <p className="empty-state">Nothing decayed/pruned/consolidated yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
