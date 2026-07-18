import { useCallback, useEffect, useState } from "react";
import { listMemories, runConsolidation, runDecay } from "../api";
import BenchmarkChart from "./BenchmarkChart";

const POLL_MS = 5000;

export default function MemoryTimeline({ userId }) {
  const [memories, setMemories] = useState([]);
  const [error, setError] = useState(null);
  const [showBenchmark, setShowBenchmark] = useState(false);
  const [jobStatus, setJobStatus] = useState(null);
  const [jobRunning, setJobRunning] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(() => {
    setRefreshing(true);
    listMemories(userId, true)
      .then(setMemories)
      .catch((err) => setError(err.message))
      .finally(() => setRefreshing(false));
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
    setJobRunning(true);
    setJobStatus("running decay job...");
    try {
      const res = await runDecay(userId);
      setJobStatus(`decay job -- recomputed ${res.detail.recomputed}, pruned ${res.detail.pruned}`);
      refresh();
    } catch (err) {
      setJobStatus(`decay job failed: ${err.message}`);
    } finally {
      setJobRunning(false);
    }
  }

  async function handleRunConsolidation() {
    setJobRunning(true);
    setJobStatus("running consolidation pass...");
    try {
      const res = await runConsolidation(userId);
      setJobStatus(`consolidation -- merged ${res.detail.consolidated_count} clusters, retired ${res.detail.retired_count} superseded`);
      refresh();
    } catch (err) {
      setJobStatus(`consolidation failed: ${err.message}`);
    } finally {
      setJobRunning(false);
    }
  }

  return (
    <div className="timeline-view">
      <div className="timeline-toolbar">
        <button className={`icon-btn ${refreshing ? "spinning" : ""}`} onClick={refresh} title="Refresh">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path d="M4 4v6h6M20 20v-6h-6M4.5 15a8 8 0 0 0 14.5 3M19.5 9A8 8 0 0 0 5 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Refresh
        </button>
        <button className="icon-btn" onClick={handleRunDecay} disabled={jobRunning}>
          Run decay job
        </button>
        <button className="icon-btn" onClick={handleRunConsolidation} disabled={jobRunning}>
          Run consolidation pass
        </button>
        <button className={showBenchmark ? "icon-btn toggle active" : "icon-btn toggle"} onClick={() => setShowBenchmark((v) => !v)}>
          {showBenchmark ? "Hide benchmark chart" : "Show benchmark chart"}
        </button>
      </div>

      {jobStatus && <div className="job-status">{jobStatus}</div>}
      {error && <div className="error-banner">{error}</div>}

      {showBenchmark && <BenchmarkChart />}

      <div className="timeline-columns">
        <section className="timeline-column">
          <h3>
            Active memories <span className="count-pill">{active.length}</span>
          </h3>
          <div className="memory-list">
            {active.map((m, i) => (
              <div
                key={m.id}
                className={`memory-card ${m.memory_type}`}
                style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}
              >
                <div className="memory-card-header">
                  <span className={`type-chip ${m.memory_type}`}>{m.memory_type}</span>
                  <span className="salience-label">{m.salience.toFixed(3)}</span>
                </div>
                <p className="memory-content">{m.content}</p>
                <div className="salience-bar-track">
                  <div className={`salience-bar-fill ${m.memory_type}`} style={{ width: `${Math.min(100, m.salience * 100)}%` }} />
                </div>
                <div className="memory-meta">
                  importance {m.importance_score.toFixed(2)} &middot; recalled {m.recall_count}&times; &middot; last{" "}
                  {new Date(m.last_recalled_at).toLocaleString()}
                </div>
              </div>
            ))}
            {active.length === 0 && <p className="empty-state-small">No active memories yet -- chat with Synapse first.</p>}
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
                <p className="memory-content strike">{m.content}</p>
                <div className="memory-meta">
                  {m.pruned_at && `pruned ${new Date(m.pruned_at).toLocaleString()}`}
                  {m.source_memory_ids?.length > 0 && ` -- merged from ${m.source_memory_ids.length} memories`}
                </div>
              </div>
            ))}
            {recentlyChanged.length === 0 && (
              <p className="empty-state-small">Nothing decayed/pruned/consolidated yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
