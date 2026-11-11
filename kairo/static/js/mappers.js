/** Turn /api/all into the numbers the cards show. Missing state must not look like a real zero when the book has cycles. */

export function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function activeCount(agents, now) {
  let n = 0;
  for (const a of agents || []) {
    const t = Date.parse(a && a.ts);
    if (!Number.isFinite(t)) continue;
    if (now - t < 5 * 60 * 1000) n += 1;
  }
  return n;
}

export function scoutCounts(agent, summary, cycles) {
  const c = (agent && agent.counters) || {};
  let pairs = num(c.candidates);
  let scanned = num(c.mints_seen);
  const last = (cycles || [])[0];
  if (scanned == null && last) scanned = num(last.scanned);
  if (pairs == null && last) pairs = num(last.scanned);
  if (scanned == null && summary) scanned = num(summary.scanned);
  return {
    pairs: pairs == null ? null : pairs,
    scanned: scanned == null ? null : scanned,
  };
}

export function modelLine(status) {
  if (!status) return { name: null, present: false };
  return { name: status.model || null, present: !!status.model_present };
}
