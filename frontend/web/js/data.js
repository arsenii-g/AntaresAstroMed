// Merge HTTP history and WebSocket readings without replaying old data as live.
export function mergeReadings(current, incoming, limit = 48) {
  const byTime = new Map(current.map((m) => [`${m.device_id}|${m.ts}`, m]));
  for (const m of incoming) {
    if (Number.isFinite(Date.parse(m.ts))) byTime.set(`${m.device_id}|${m.ts}`, m);
  }
  return [...byTime.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts)).slice(-limit);
}

export function sparkPath(values, low, high) {
  let connected = false;
  return values.map((value, i) => {
    if (typeof value !== "number" || !Number.isFinite(value)) { connected = false; return ""; }
    const command = connected ? "L" : "M";
    connected = true;
    return `${command}${i / Math.max(1, values.length - 1) * 100},${40 - (value - low) / (high - low || 1) * 36}`;
  }).join(" ");
}
