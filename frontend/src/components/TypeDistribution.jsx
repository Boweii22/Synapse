import { motion } from "framer-motion";

const TYPES = ["semantic", "episodic", "consolidated"];

export default function TypeDistribution({ memories }) {
  const total = memories.length || 1;
  const counts = { episodic: 0, semantic: 0, consolidated: 0 };
  for (const m of memories) counts[m.memory_type] = (counts[m.memory_type] || 0) + 1;

  const segments = TYPES.map((type) => ({ type, count: counts[type], pct: (counts[type] / total) * 100 }));

  return (
    <div className="type-distribution">
      <div className="type-distribution-track">
        {segments.map(
          (s) =>
            s.count > 0 && (
              <motion.div
                key={s.type}
                className={`type-distribution-segment ${s.type}`}
                initial={{ width: 0 }}
                animate={{ width: `${s.pct}%` }}
                transition={{ duration: 0.5, ease: "easeOut" }}
              />
            )
        )}
      </div>
      <div className="type-distribution-legend">
        {segments.map((s) => (
          <span key={s.type} className="legend-item">
            <span className={`legend-dot ${s.type}`} />
            {s.type} <strong>{s.count}</strong>
          </span>
        ))}
      </div>
    </div>
  );
}
