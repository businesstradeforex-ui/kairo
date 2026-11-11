import { axisTicks, badgeDelta, downsample, isUp, segments, sliceRange } from "./chart-math.js";

const UP = "#32D74B";
const DOWN = "#FF453A";

export function prepareSeries(raw, rangeKey, now, bankrollUsd) {
  const sliced = sliceRange(raw, rangeKey, now);
  const segs = segments(sliced, rangeKey).map((s) => downsample(s, 160));
  const flat = segs.flat();
  return {
    segments: segs,
    flat,
    up: isUp(flat, rangeKey, bankrollUsd),
    delta: badgeDelta(flat, rangeKey, bankrollUsd),
    ticks: axisTicks(flat, rangeKey),
  };
}

export function drawChart(canvas, series) {
  const wrap = canvas.parentElement;
  const cssW = Math.max(1, wrap.clientWidth);
  const cssH = Math.max(1, canvas.clientHeight || 190);
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const pxW = Math.round(cssW * dpr);
  const pxH = Math.round(cssH * dpr);
  if (canvas.width !== pxW || canvas.height !== pxH) {
    canvas.width = pxW;
    canvas.height = pxH;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const pts = series.flat;
  if (pts.length < 2) {
    ctx.strokeStyle = "rgba(142,142,147,.45)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(12, cssH / 2);
    ctx.lineTo(cssW - 12, cssH / 2);
    ctx.stroke();
    return { map: [], cssW, cssH };
  }
  const padL = 8, padR = 8, padT = 16, padB = 22;
  let lo = Infinity, hi = -Infinity, t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  for (const p of pts) {
    if (p.equity < lo) lo = p.equity;
    if (p.equity > hi) hi = p.equity;
  }
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const span = Math.max(1, t1 - t0);
  const xOf = (t) => padL + ((t - t0) / span) * (cssW - padL - padR);
  const yOf = (v) => padT + (1 - (v - lo) / (hi - lo)) * (cssH - padT - padB);
  const col = series.up ? UP : DOWN;
  ctx.lineWidth = 2.25;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = col;
  ctx.beginPath();
  let started = false;
  const map = [];
  for (const seg of series.segments) {
    if (seg.length < 2) continue;
    ctx.moveTo(xOf(seg[0].t), yOf(seg[0].equity));
    for (let i = 1; i < seg.length; i++) ctx.lineTo(xOf(seg[i].t), yOf(seg[i].equity));
    started = true;
    for (const p of seg) map.push({ x: xOf(p.t), y: yOf(p.equity), t: p.t, equity: p.equity });
  }
  if (started) ctx.stroke();
  const last = pts[pts.length - 1];
  const lx = xOf(last.t), ly = yOf(last.equity);
  ctx.beginPath();
  ctx.fillStyle = col;
  ctx.arc(lx, ly, 4.2, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#000";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "rgba(142,142,147,.95)";
  ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "center";
  for (const tick of series.ticks) {
    const x = xOf(tick.t);
    ctx.fillText(tick.label, Math.max(28, Math.min(cssW - 28, x)), cssH - 4);
  }
  return { map, cssW, cssH, last: { x: lx, y: ly } };
}

export function hitTest(map, x) {
  if (!map || !map.length) return null;
  let best = map[0], dist = Math.abs(map[0].x - x);
  for (const p of map) {
    const d = Math.abs(p.x - x);
    if (d < dist) { best = p; dist = d; }
  }
  return best;
}
