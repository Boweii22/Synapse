import { motion } from "framer-motion";

// A small live line chart of active memory count over this session -- real
// data sampled every poll, not decorative. Watching the line actually move
// as you chat is the point.
export default function MemoryHistoryChart({ history }) {
  if (history.length < 2) {
    return <div className="history-chart-empty">Collecting live data&hellip;</div>;
  }

  const width = 600;
  const height = 56;
  const padding = 4;
  const counts = history.map((h) => h.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts, 0);
  const range = Math.max(max - min, 1);

  const points = history.map((h, i) => {
    const x = padding + (i / (history.length - 1)) * (width - padding * 2);
    const y = height - padding - ((h.count - min) / range) * (height - padding * 2);
    return [x, y];
  });

  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p[0]},${p[1]}`).join(" ");
  const areaPath = `${linePath} L${points[points.length - 1][0]},${height} L${points[0][0]},${height} Z`;
  const current = counts[counts.length - 1];
  const first = counts[0];
  const delta = current - first;

  return (
    <div className="history-chart">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="history-chart-svg">
        <motion.path
          d={areaPath}
          className="history-chart-area"
          initial={false}
          animate={{ d: areaPath }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
        <motion.path
          d={linePath}
          className="history-chart-line"
          fill="none"
          initial={false}
          animate={{ d: linePath }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
        <circle cx={points[points.length - 1][0]} cy={points[points.length - 1][1]} r="2.5" className="history-chart-dot" />
      </svg>
      <div className="history-chart-labels">
        <span>active memories, this session</span>
        <span className="history-chart-current">
          {current}
          {delta !== 0 && (
            <span className={delta > 0 ? "history-chart-delta up" : "history-chart-delta down"}>
              {delta > 0 ? "+" : ""}
              {delta}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}
