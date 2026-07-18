import { useEffect, useState } from "react";
import { benchmarkChartUrl, fetchBenchmarkData } from "../api";

export default function BenchmarkChart() {
  const [available, setAvailable] = useState(null);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    fetchBenchmarkData()
      .then((data) => {
        setAvailable(true);
        const checkpoints = data.checkpoints || [];
        const contradiction = checkpoints.filter((c) => c.category === "contradiction");
        const synapseAcc = contradiction.length
          ? contradiction.filter((c) => c.synapse_correct).length / contradiction.length
          : null;
        const naiveAcc = contradiction.length
          ? contradiction.filter((c) => c.naive_correct).length / contradiction.length
          : null;
        setSummary({ synapseAcc, naiveAcc, totalCheckpoints: checkpoints.length });
      })
      .catch(() => setAvailable(false));
  }, []);

  if (available === null) return <div className="benchmark-panel">Loading benchmark results...</div>;

  if (available === false) {
    return (
      <div className="benchmark-panel">
        <p>
          Benchmark hasn't been run yet. Run <code>backend/benchmark/run_benchmark.py</code> to generate it.
        </p>
      </div>
    );
  }

  return (
    <div className="benchmark-panel">
      <img src={benchmarkChartUrl()} alt="Synapse vs naive baseline benchmark chart" className="benchmark-image" />
      {summary && summary.synapseAcc !== null && (
        <p className="benchmark-summary">
          Contradiction-question accuracy (e.g. "where do I live now?") -- Synapse:{" "}
          <strong>{(summary.synapseAcc * 100).toFixed(0)}%</strong>, Naive baseline:{" "}
          <strong>{(summary.naiveAcc * 100).toFixed(0)}%</strong>, across {summary.totalCheckpoints} LLM-judged checkpoints.
        </p>
      )}
    </div>
  );
}
