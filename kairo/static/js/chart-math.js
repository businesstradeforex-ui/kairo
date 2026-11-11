/** Pure equity-curve math. No DOM. Times are epoch milliseconds. */

export const RANGES = {
  live: 30 * 60 * 1000,
  "1h": 60 * 60 * 1000,
  "4h": 4 * 60 * 60 * 1000,
  "1d": 24 * 60 * 60 * 1000,
  "1w": 7 * 24 * 60 * 60 * 1000,
  all: Infinity,
};

export function normalize(points) {
  const out = [];
  for (const p of points || []) {
    const t = typeof p.t === "number" ? p.t : Date.parse(p.ts);
    const equity = Number(p.equity);
    if (!Number.isFinite(t) || !Number.isFinite(equity)) continue;
    if (out.length && out[out.length - 1].t === t) out[out.length - 1] = { t, equity };
    else out.push({ t, equity });
  }
  out.sort((a, b) => a.t - b.t);
  const dedup = [];
  for (const p of out) {
    if (dedup.length && dedup[dedup.length - 1].t === p.t) dedup[dedup.length - 1] = p;
    else dedup.push(p);
  }
  return dedup;
}

/** Points inside the window. The last sample before the window is carried to the edge so the line does not start from nothing. Large holes are not filled. */
export function sliceRange(points, rangeKey, now) {
  const all = normalize(points);
  const win = RANGES[rangeKey] ?? RANGES.all;
  if (!all.length) return [];
  if (!Number.isFinite(win)) return all;
  const cut = now - win;
  const before = all.filter((p) => p.t < cut);
  const inside = all.filter((p) => p.t >= cut && p.t <= now + 2000);
  if (!inside.length) return before.length ? [before[before.length - 1]] : [];
  if (before.length) return [{ t: cut, equity: before[before.length - 1].equity }, ...inside];
  return inside;
}

export function gapLimit(rangeKey) {
  const win = RANGES[rangeKey] ?? RANGES.all;
  if (!Number.isFinite(win)) return 6 * 60 * 60 * 1000;
  return Math.max(win * 0.25, 90 * 1000);
}

/** Split so a missing stretch is not drawn as a straight spike. */
export function segments(points, rangeKey) {
  const maxGap = gapLimit(rangeKey);
  const segs = [];
  let cur = [];
  for (const p of points) {
    if (cur.length && p.t - cur[cur.length - 1].t > maxGap) {
      segs.push(cur);
      cur = [];
    }
    cur.push(p);
  }
  if (cur.length) segs.push(cur);
  return segs;
}

export function rangeDelta(points) {
  if (!points || points.length < 1) return null;
  return points[points.length - 1].equity - points[0].equity;
}

/** Badge value in USD. For the full history it is equity minus starting capital, same number as the header. */
export function badgeDelta(points, rangeKey, bankrollUsd) {
  if (!points || !points.length) return null;
  if (rangeKey === "all" && Number.isFinite(bankrollUsd)) {
    return points[points.length - 1].equity - bankrollUsd;
  }
  return rangeDelta(points);
}

export function isUp(points, rangeKey, bankrollUsd) {
  const d = badgeDelta(points, rangeKey, bankrollUsd);
  if (d == null) return true;
  return d >= -0.005;
}

export function axisTicks(points, rangeKey) {
  if (!points.length) return [];
  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const span = Math.max(1, t1 - t0);
  const n = 4;
  const ticks = [];
  for (let i = 0; i < n; i++) {
    const t = t0 + (span * i) / (n - 1);
    ticks.push({ t, label: formatTick(t, rangeKey, span) });
  }
  return ticks;
}

export function formatTick(t, rangeKey, span) {
  const d = new Date(t);
  const hm = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).format(d);
  const day = new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", timeZone: "Europe/Paris" }).format(d);
  if (rangeKey === "live" || rangeKey === "1h" || rangeKey === "4h") return hm;
  if (rangeKey === "1d") return hm;
  if (span < 36 * 60 * 60 * 1000) return `${day} ${hm}`;
  return day;
}

export function downsample(points, maxPoints) {
  if (points.length <= maxPoints) return points;
  const out = [points[0]];
  const step = (points.length - 1) / (maxPoints - 1);
  for (let i = 1; i < maxPoints - 1; i++) out.push(points[Math.round(i * step)]);
  out.push(points[points.length - 1]);
  return out;
}
