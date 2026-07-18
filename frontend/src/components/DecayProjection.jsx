// Projects a memory's salience forward using the same exponential decay
// formula the backend actually runs (salience(t) = salience_now * e^-λt),
// so this is a real projection of the mechanism, not a decorative squiggle.
// Half-lives mirror backend/app/config.py defaults.
const HALF_LIFE_HOURS = { episodic: 72, semantic: 720, consolidated: 720 };
const PRUNE_FLOOR = 0.05;

function projectCurve(salienceNow, memoryType) {
  const halfLife = HALF_LIFE_HOURS[memoryType] ?? 720;
  const lambda = Math.log(2) / halfLife;
  const horizonHours = memoryType === "episodic" ? 24 * 14 : 24 * 60;
  const steps = 24;
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const hours = (i / steps) * horizonHours;
    points.push({ hours, salience: salienceNow * Math.exp(-lambda * hours) });
  }
  const daysToFloor = salienceNow > PRUNE_FLOOR ? Math.log(salienceNow / PRUNE_FLOOR) / lambda / 24 : 0;
  return { points, horizonHours, daysToFloor };
}

export default function DecayProjection({ salience, memoryType }) {
  const { points, horizonHours, daysToFloor } = projectCurve(salience, memoryType);
  const width = 120;
  const height = 28;
  const max = Math.max(points[0].salience, PRUNE_FLOOR * 2);

  const toXY = (p) => [(p.hours / horizonHours) * width, height - (Math.min(p.salience, max) / max) * height];
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${toXY(p).join(",")}`).join(" ");
  const floorY = height - (PRUNE_FLOOR / max) * height;

  const horizonLabel = memoryType === "episodic" ? "14d" : "60d";
  const projectionLabel =
    daysToFloor > 0 && daysToFloor * 24 < horizonHours
      ? `prunes in ~${daysToFloor < 1 ? "<1" : Math.round(daysToFloor)}d if not recalled`
      : `stable past ${horizonLabel} if not recalled`;

  return (
    <div className="decay-projection">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="decay-projection-svg">
        <line x1="0" y1={floorY} x2={width} y2={floorY} className="decay-projection-floor" />
        <path d={linePath} className={`decay-projection-line ${memoryType}`} fill="none" />
      </svg>
      <span className="decay-projection-label">{projectionLabel}</span>
    </div>
  );
}
