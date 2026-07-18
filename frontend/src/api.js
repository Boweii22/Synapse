const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res;
}

export async function createUser() {
  const res = await request("/users", { method: "POST" });
  return res.json();
}

export async function sendChat(userId, message) {
  const res = await request("/chat", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, message }),
  });
  return res.json();
}

export async function listMemories(userId, includeInactive = true) {
  const res = await request(`/memories/${userId}?include_inactive=${includeInactive}`);
  return res.json();
}

export async function runDecay(userId) {
  const res = await request(`/memories/${userId}/run-decay`, { method: "POST" });
  return res.json();
}

export async function runConsolidation(userId) {
  const res = await request(`/memories/${userId}/run-consolidation`, { method: "POST" });
  return res.json();
}

export function benchmarkChartUrl() {
  return `${API_BASE_URL}/benchmark/chart`;
}

export async function fetchBenchmarkData() {
  const res = await request("/benchmark/data");
  return res.json();
}
