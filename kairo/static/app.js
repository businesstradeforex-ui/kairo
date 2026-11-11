"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fr2 = n => Number(n).toLocaleString("fr-FR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
let FX = 1.08, BANK = 1080, BANK_EUR = 1000; // USD per EUR (live, from /api/all); portfolio shown in EUR
const usd = (n, sign) => { if (n == null || isNaN(n)) return "—"; n = n / FX; const s = n < 0 ? "-" : (sign ? "+" : ""); return s + fr2(Math.abs(n)) + " €"; };
const usdK = n => { if (n == null) return "—"; n = +n / FX; return n >= 1e6 ? (n/1e6).toLocaleString("fr-FR",{maximumFractionDigits:2}) + " M€" : n >= 1e3 ? Math.round(n/1e3).toLocaleString("fr-FR") + " k€" : fr2(n) + " €"; };
const pct = (n, sign = true) => n == null || isNaN(n) ? "—" : (sign && n > 0 ? "+" : "") + Number(n).toLocaleString("fr-FR", {maximumFractionDigits: 1, minimumFractionDigits: 1}) + " %";
const price = p => { if (!p) return "—"; p = +p; if (p >= 1) return "$" + fr2(p); const d = Math.max(2, Math.ceil(-Math.log10(p)) + 3); return "$" + p.toLocaleString("fr-FR", {maximumFractionDigits: Math.min(d, 12), minimumFractionDigits: Math.min(d, 12)}); };
const hhmm = ts => ts ? new Date(ts).toLocaleTimeString("fr-FR", {hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris"}) : "";
const avatar = (icon, sym) => icon ? `<div class="av" style="background-image:url('${esc(icon)}')"></div>` : `<div class="av">${esc((sym||"?").slice(0,2).toUpperCase())}</div>`;
const CK = {cycle:"cycle",candidates:"candidats",mints_seen:"mints scannés",new_discovered:"nouveaux",watchlist:"surveillés",pairs_fetched:"paires lues",in:"entrants",killed:"éliminés",survivors:"survivants",top_reason:"motif n°1",scored:"notés",passed_70:"validés",passed:"validés",seuil:"seuil",entries:"entrées",equity:"equity",open:"ouvertes",exits:"sorties",exits_tick:"sorties",cycles:"cycles",kill_rows:"lignes de kill"};
let D = null, tf = "live", seen = null, actFilter = "all";
const seuil = () => (D && D.config && D.config.analyst && D.config.analyst.seuil) || 70;
const profileName = () => (D && ((D.config && D.config.profile) || (D.summary && D.summary.profile))) || "profit";
const profileLabel = () => (D && ((D.config && D.config.profile_label) || (D.summary && D.summary.profile_label))) || "Mode profit";
function setModeBadges() {
  const name = profileName(), label = (profileLabel() || "").toUpperCase();
  document.querySelectorAll(".badge-mode").forEach(el => {
    el.textContent = label || (name === "strict" ? "MODE STRICT" : "MODE AGRESSIF");
    el.className = "badge-mode " + name;
  });
}

/* ---------- odometer ---------- */
function setBalance(v) {
  const el = $("#balance"), txt = fr2(v / FX) + " €";
  if (el.dataset.v === txt) return;
  const old = el.dataset.v || ""; el.dataset.v = txt;
  if (old.length !== txt.length) {
    el.innerHTML = [...txt].map(ch => /\d/.test(ch) ? `<span class="d"><span class="col">${[...Array(10).keys()].map(i => `<span>${i}</span>`).join("")}</span></span>` : `<span class="s">${ch}</span>`).join("");
  }
  const cols = el.querySelectorAll(".d .col"); let i = 0;
  [...txt].forEach(ch => { if (/\d/.test(ch)) { cols[i++].style.transform = `translateY(-${+ch * 56}px)`; } });
}

/* ---------- toasts ---------- */
function toast(text) {
  const t = document.createElement("div"); t.className = "toast";
  t.innerHTML = `<img class="bot-av" src="/logo.svg" alt=""><div><div class="tt">Kairo</div><div class="tb">${text}</div></div>`;
  $("#toasts").prepend(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 450); }, 5200);
}
function checkToasts(act) {
  const trades = act.filter(e => e.type !== "kill");
  if (seen === null) { seen = new Set(trades.map(e => e.id)); return; }
  trades.slice().reverse().forEach(e => {
    if (seen.has(e.id)) return; seen.add(e.id);
    const sym = esc(e.symbol);
    if (e.type === "buy") toast(`Acheté ${sym} · ${usd(e.amount)}`);
    else if (e.type === "stop") toast(`${sym} a touché le stop -6 % · <span class="red">${usd(e.amount, true)}</span>`);
    else toast(`Vendu ${sym} · <span class="${e.amount >= 0 ? "green" : "red"}">${usd(e.amount, true)} (${pct(e.pnl_pct)})</span>`);
  });
}

/* ---------- equity chart (smooth spline) ---------- */
function drawEquity(curve) {
  const svg = $("#eqchart"), W = 400, H = 190, pad = 14;
  const now = Date.now(), win = {live: 30*60e3, "1h": 3600e3, "4h": 4*3600e3, "1d": 864e5, "1w": 7*864e5, all: Infinity}[tf];
  curve = curve.slice().sort((a, b) => new Date(a.ts) - new Date(b.ts));
  let pts = curve.filter(p => now - new Date(p.ts) <= win);
  if (pts.length < 2) pts = curve.slice(-2);
  if (pts.length > 120) { const step = pts.length / 120; pts = [...Array(120).keys()].map(i => pts[Math.floor(i * step)]).concat([curve[curve.length - 1]]); pts = pts.filter((p, i) => !i || p !== pts[i-1]); }
  if (!pts.length) { svg.innerHTML = ""; return; }
  const ys = pts.map(p => p.equity); let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi - lo < 1) { lo -= 5; hi += 5; }
  const t0 = new Date(pts[0].ts).getTime(), t1 = new Date(pts[pts.length - 1].ts).getTime() || t0 + 1;
  const xy = pts.map((p, i) => [pts.length === 1 ? W/2 : pad + (W - 2*pad - 40) * (t1 > t0 ? (new Date(p.ts) - t0) / (t1 - t0) : i / (pts.length - 1)), pad + 20 + (H - 2*pad - 30) * (1 - (p.equity - lo) / (hi - lo))]);
  let d = `M${xy[0][0]},${xy[0][1]}`;
  // monotone curve: control points stay between neighbours in x (never goes back in time) and in y (no overshoot)
  for (let i = 0; i < xy.length - 1; i++) { const p0 = xy[i-1] || xy[i], p1 = xy[i], p2 = xy[i+1], p3 = xy[i+2] || p2;
    const dx = (p2[0] - p1[0]) / 3, lo2 = Math.min(p1[1], p2[1]), hi2 = Math.max(p1[1], p2[1]), cl = v => Math.max(lo2, Math.min(hi2, v));
    const m1 = (p2[0] - p0[0]) ? (p2[1] - p0[1]) / (p2[0] - p0[0]) : 0, m2 = (p3[0] - p1[0]) ? (p3[1] - p1[1]) / (p3[0] - p1[0]) : 0;
    d += ` C${p1[0] + dx},${cl(p1[1] + m1 * dx)} ${p2[0] - dx},${cl(p2[1] - m2 * dx)} ${p2[0]},${p2[1]}`; }
  const up = pts[pts.length-1].equity >= pts[0].equity, col = up ? "#32D74B" : "#FF453A";
  const last = xy[xy.length - 1], every = Math.max(1, Math.ceil(xy.length / 14));
  svg.innerHTML = `<defs><linearGradient id="gf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col}" stop-opacity=".38"/><stop offset="1" stop-color="#000" stop-opacity="0"/></linearGradient></defs>
    <path d="${d} L${last[0]},${H} L${xy[0][0]},${H} Z" fill="url(#gf)"/>
    <path d="${d}" fill="none" stroke="${col}" stroke-width="2.4" stroke-linecap="round"/>
    ${xy.filter((_, i) => i % every === 0).map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="2.2" fill="${col}" opacity=".7"/>`).join("")}
    <circle cx="${last[0]}" cy="${last[1]}" r="9" fill="${col}" opacity=".2"><animate attributeName="r" values="5;11;5" dur="1.8s" repeatCount="indefinite"/></circle>
    <circle cx="${last[0]}" cy="${last[1]}" r="4.5" fill="${col}" stroke="#000" stroke-width="2"/>`;
  const dl = pts[pts.length-1].equity - (pts.length > 1 ? pts[pts.length-2].equity : pts[0].equity);
  const lp = $("#lastpill"), r = svg.getBoundingClientRect();
  lp.textContent = usd(dl, true); lp.className = "lastpill" + (dl < 0 ? " down" : "");
  lp.style.left = (last[0] / W * r.width + 6) + "px"; lp.style.top = (last[1] / H * r.height) + "px";
}

/* ---------- agent cards ---------- */
const AG = {scout: "📡", filter: "🧹", analyst: "🧠", executor: "🤖", risk: "🎯", logger: "📒"};
function stBadge(a) { const on = a.status === "running" || a.status === "monitoring"; return `<div class="st ${on ? "" : "idle"}"><i></i>${esc(a.status_fr || "—")}</div>`; }
function agentCards() {
  const A = Object.fromEntries(D.agents.map(a => [a.id, a])), S = D.summary, feed = D.scout_feed.lines || [];
  const kills = D.activity.filter(e => e.type === "kill").slice(0, 5);
  const top = (D.scores || [])[0], pos = D.positions.open, lastBuy = D.activity.find(e => e.type === "buy");
  const lastExit = D.activity.find(e => e.type === "sell" || e.type === "stop");
  const feedHtml = arr => arr.length ? arr.map(l => `<div><b>${esc(l.symbol)}</b><span class="${l.kind === "pass" ? "p" : "k"} x">${esc(l.text_fr)}</span></div>`).join("") : `<div class="x">en attente du prochain cycle…</div>`;
  const sc = top ? top.score : 0, C = 2 * Math.PI * 44;
  const cards = {
    scout: `<div class="as">${(A.scout.counters || {}).candidates ?? 0} paires dans la fenêtre · ${(A.scout.counters || {}).mints_seen ?? 0} scannées</div><div class="feed" style="margin-top:8px">${feedHtml(feed.slice(0, 5))}</div>`,
    filter: `<div class="big">${S.killed_tokens ?? 0} <span class="muted small">tokens éliminés</span></div><div class="feed">${kills.length ? kills.slice(0,4).map(k => `<div><b>${esc(k.symbol)}</b><span class="k x">${esc(k.detail)}</span></div>`).join("") : '<div class="x">aucune élimination</div>'}</div>`,
    analyst: `<div class="gauge"><svg viewBox="0 0 110 110"><circle cx="55" cy="55" r="44" fill="none" stroke="rgba(255,159,10,.18)" stroke-width="10"/><circle cx="55" cy="55" r="44" fill="none" stroke="${sc >= seuil() ? "#32D74B" : "#FF9F0A"}" stroke-width="10" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - sc/100)}" transform="rotate(-90 55 55)" style="transition:stroke-dashoffset 1s"/><text x="55" y="58" text-anchor="middle" fill="#fff" font-size="28" font-weight="700">${top ? Math.round(sc) : "–"}</text><text x="55" y="76" text-anchor="middle" fill="#8E8E93" font-size="11">${esc(top ? top.symbol : "")}</text></svg>
      <div class="gt">${A.analyst.status === "running" ? "notation…" : "dernière notation"}<br>${S.scores ?? 0} notes · ${S.passes ?? 0} validés<br>seuil <b style="color:#fff">${seuil()}</b>${(D.config && D.config.analyst && D.config.analyst.signals) ? "<br>ou signal rapide" : ""}</div></div>`,
    executor: lastBuy ? `<div class="tok">${avatar(lastBuy.icon, lastBuy.symbol)}<div><div class="an">${esc(lastBuy.symbol)}</div><div class="as">${hhmm(lastBuy.ts)}${lastBuy.trigger_fr ? " · " + esc(lastBuy.trigger_fr) : ""}</div></div></div><div class="big">${usd(lastBuy.amount)}<span class="muted small"> · ${pct(lastBuy.amount / BANK * 100, false)} du capital</span></div><div class="pills"><span class="pill g">✓ rempli · papier</span><span class="pill n">max 8 %</span>${lastBuy.trigger_fr ? `<span class="pill o">${esc(lastBuy.trigger_fr)}</span>` : ""}</div>`
      : `<div class="as">Aucun ordre pour l'instant — en attente d'un score ≥ ${seuil()}${(D.config && D.config.analyst && D.config.analyst.signals) ? " ou d'un signal" : ""}.</div><div class="pills"><span class="pill n">3–8 % par trade</span><span class="pill o">papier</span></div>`,
    risk: pos.length ? `<div class="tok">${avatar(pos[0].icon, pos[0].symbol)}<div><div class="an">${esc(pos[0].symbol)}</div><div class="as">surveillance · stop ${price(pos[0].stop_price)}</div></div></div><div class="big ${pos[0].pnl_pct >= 0 ? "green" : "red"}">${pct(pos[0].pnl_pct)}</div><div class="pills"><span class="pill r">-6 %</span><span class="pill ${pos[0].trail_active ? "g" : "n"}">trail 6 %${pos[0].trail_active ? " · actif" : ""}</span><span class="pill n">${pos.length} ouverte(s)</span></div>`
      : lastExit ? `<div class="tok">${avatar(lastExit.icon, lastExit.symbol)}<div><div class="an">${esc(lastExit.symbol)}</div><div class="as">${lastExit.type === "stop" ? "Sorti au stop -6 %" : "Sorti au trailing"}</div></div></div><div class="big ${lastExit.amount >= 0 ? "green" : "red"}">${usd(lastExit.amount, true)}</div><div class="pills"><span class="pill r">-6 %</span><span class="pill g">trail 6 %</span></div>`
      : `<div class="as">Aucune position à surveiller.</div><div class="pills"><span class="pill r">stop -6 %</span><span class="pill g">trail 6 % après +12 %</span></div>`,
    logger: `<div class="big">${(S.kill_rows ?? 0) + (S.scores ?? 0) + (S.trades ?? 0)} <span class="muted small">événements</span></div><div class="feed">${D.activity.slice(0,4).map(e => `<div><b>${esc(e.title_fr)}</b><span class="x">${hhmm(e.ts)}</span></div>`).join("")}</div>`,
  };
  const subs = {scout: "Découverte", filter: "Sécurité", analyst: "Notation 0–100", executor: "Ordres papier", risk: "Stops", logger: "Journal"};
  const html = D.agents.map(a => `<div class="acard"><div class="ah"><div class="em">${AG[a.id]}</div><div><div class="an">${a.name}</div><div class="as">${subs[a.id]}</div></div>${stBadge(a)}</div>${cards[a.id]}</div>`).join("");
  const car = $("#carousel"), sl = car.scrollLeft; if (car._h !== html) { car._h = html; car.innerHTML = html; car.scrollLeft = sl; }
  if (!$("#cdots").children.length) $("#cdots").innerHTML = D.agents.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("");
  const n = D.agents.filter(a => a.ts && Date.now() - new Date(a.ts) < 5 * 60e3).length;
  $("#nactifs").textContent = `${n} actifs`;
}
$("#carousel").addEventListener("scroll", () => { const c = $("#carousel"), w = c.firstElementChild ? c.firstElementChild.offsetWidth + 12 : 1, i = Math.round(c.scrollLeft / w);
  [...$("#cdots").children].forEach((d, j) => d.classList.toggle("on", j === i)); }, {passive: true});

/* ---------- activity ---------- */
function actRow(e) {
  let ra = "", rs = "", cls = "";
  if (e.type === "buy") { ra = usd(e.amount); rs = pct(e.amount / BANK * 100, false) + " du capital"; }
  else if (e.type === "sell" || e.type === "stop") { ra = usd(e.amount, true); cls = e.amount >= 0 ? "green" : "red"; rs = pct(e.pnl_pct); }
  else { ra = `<span class="red">✕</span>`; rs = esc(e.detail); }
  const sub = e.type === "kill" ? `Filter · ${esc(e.reason_fr)} · ${hhmm(e.ts)}` : e.type === "buy" ? `Executor${e.trigger_fr ? " · " + esc(e.trigger_fr) : (e.detail ? " · " + esc(e.detail) : "")} · ${hhmm(e.ts)}` : `Risk · ${esc(e.detail)} · ${hhmm(e.ts)}`;
  return `<div class="row" data-mint="${esc(e.mint)}">${avatar(e.icon, e.symbol)}<div class="mid"><div class="mt">${esc(e.title_fr)}</div><div class="ms">${sub}</div></div><div class="rt"><div class="ra ${cls}">${ra}</div><div class="rs">${rs}</div></div></div>`;
}
function renderActivity() {
  const home = D.activity.slice(0, 8);
  const h = home.length ? home.map(actRow).join("") : `<div class="empty">Le desk démarre…</div>`; if ($("#act-home")._h !== h) { $("#act-home")._h = h; $("#act-home").innerHTML = h; }
}

/* ---------- other tabs ---------- */
function renderAgentsTab() {
  const H = D.handoffs.filter(h => h.from);
  const order = ["scout","filter","analyst","executor","risk","logger"];
  $("#pipeline").innerHTML = order.map((a, i) => `<div class="pnode"><div class="e">${AG[a]}</div>${a[0].toUpperCase() + a.slice(1)}</div>${i < 5 ? `<div class="parrow">${H[i] ? H[i].count : 0}</div>` : ""}`).join("");
  $("#agents-full").innerHTML = D.agents.map(a => `<div class="card afull"><div class="acard" style="padding:0;min-height:0;background:none"><div class="ah"><div class="em">${AG[a.id]}</div><div><div class="an">${a.name}</div><div class="as">${esc(a.role_fr)}</div></div>${stBadge(a)}</div></div>
    <div class="small">${esc(a.last_action || "—")}</div><div class="muted tiny" style="margin-top:4px">${a.ts ? "mis à jour " + hhmm(a.ts) : ""}</div>
    <div class="kv">${Object.entries(a.counters || {}).filter(([,v]) => v != null).map(([k, v]) => `<span class="pill n">${esc(CK[k] || k)} : ${esc(k === "top_reason" ? (D.labels.reasons[v] || v) : typeof v === "number" ? v.toLocaleString("fr-FR") : v)}</span>`).join("")}</div></div>`).join("");
  const L = D.labels.components;
  $("#scores-full").innerHTML = D.scores.length ? D.scores.map(s => `<div class="srow" data-mint="${esc(s.mint)}"><div class="sh"><span>${esc(s.symbol)}</span><span class="pill ${s.passed ? "g" : "o"}">${s.score.toLocaleString("fr-FR")} ${s.passed ? "✓" : ""}</span></div>
     <div class="bars">${Object.keys(L).filter(k => k in s.components).map(k => `<div class="bar">${esc(L[k])} · ${Math.round(s.components[k])}<div class="bt"><i style="width:${s.components[k]}%"></i></div></div>`).join("")}</div>
     <div class="muted tiny" style="margin-top:6px">${esc(s.components.holder_note || "")}</div></div>`).join("") : `<div class="empty">Aucun token n'a encore survécu au Filter.</div>`;
  const kb = D.kills_by_reason, mx = Math.max(1, ...kb.map(k => k.tokens));
  $("#kbr").innerHTML = `<div class="kbr">${kb.length ? kb.map(k => `<div class="kr"><div class="kl"><span>${esc(k.reason_fr)}</span><span class="muted">${k.tokens}</span></div><div class="kt"><i style="width:${k.tokens / mx * 100}%"></i></div></div>`).join("") : '<div class="empty">—</div>'}</div><div class="muted tiny">tokens distincts par motif (un token peut cumuler plusieurs motifs)</div>`;
}
async function renderActivityTab() {
  const all = await fetch("/api/activity?all=1&limit=400").then(r => r.json());
  const f = actFilter === "all" ? all : actFilter === "kill" ? all.filter(e => e.type === "kill") : all.filter(e => e.type !== "kill");
  $("#act-full").innerHTML = f.length ? f.map(actRow).join("") : `<div class="empty">Rien pour l'instant.</div>`;
  const o = D.positions.open;
  $("#open-full").innerHTML = o.length ? o.map(p => `<div class="row" data-mint="${esc(p.mint)}">${avatar(p.icon, p.symbol)}<div class="mid"><div class="mt">${esc(p.symbol)}</div><div class="ms">${p.trigger_fr ? esc(p.trigger_fr) + " · " : ""}entrée ${price(p.entry_price)} · stop ${price(p.stop_price)}${p.trail_active ? " · trailing actif" : ""}${p.tp1_done ? " · TP 50 % fait" : ""}</div></div><div class="rt"><div class="ra ${p.pnl_usd >= 0 ? "green" : "red"}">${usd(p.pnl_usd, true)}</div><div class="rs">${pct(p.pnl_pct)}</div></div></div>`).join("") : `<div class="empty">Aucune position ouverte</div>`;
}
function renderAccount() {
  const c = D.config, S = D.summary;
  const li = (a, b) => `<div class="li"><span>${a}</span><span>${b}</span></div>`;
  $("#account").innerHTML = `<div class="acc">
   <div class="card" style="text-align:center"><div class="badges" style="align-items:center"><div class="badge-paper" style="display:inline-block">MODE PAPIER</div><div class="badge-mode ${esc(c.profile || "profit")}" style="display:inline-block">${esc((c.profile_label || "Mode profit").toUpperCase())}</div></div><div class="small muted" style="margin-top:8px">Les 6 agents décident. L'IA locale exécute seulement une liste blanche. Les vrais ordres sont coupés par défaut.</div></div>
   <h3>Résultats</h3><div class="card">${li("Capital virtuel de départ", fr2(BANK_EUR) + " €")}${li("Taux EUR/USD (live)", Number(FX).toLocaleString("fr-FR",{maximumFractionDigits:4}))}${li("Valeur actuelle", usd(S.equity))}${li("PnL", `<span class="${S.pnl_usd >= 0 ? "green" : "red"}">${usd(S.pnl_usd, true)} (${pct(S.pnl_pct)})</span>`)}${li("PnL réalisé", usd(S.realized_pnl, true))}${li("Trades", S.trades)}${li("Taux de réussite", S.win_rate == null ? "—" : pct(S.win_rate, false))}${li("Tokens scannés", S.scanned)}${li("Tokens éliminés", S.killed_tokens)}${li("Cycles", S.cycle ?? 0)}</div>
   <h3>Scout</h3><div class="card">${li("Âge des paires", c.scout.age)}${li("Market cap", c.scout.mcap)}${li("Source", c.scout.source)}</div>
   <h3>Filter · éliminations</h3><div class="card">${c.filter.map(f => li(f, "✕")).join("")}${c.filter_notes_fr.map(n => li(n, "")).join("")}</div>
   <h3>Analyst</h3><div class="card">${li("Seuil de passage", c.analyst.seuil)}${Object.entries(c.analyst.poids).map(([k, v]) => li(k, v.toLocaleString("fr-FR") + " %")).join("")}${li(c.analyst.note_fr, "")}</div>
   <h3>Executor</h3><div class="card">${li("Taille max", c.executor.max_par_trade)}${li("Exécution simulée", c.executor.fill)}</div>
   <h3>Risk</h3><div class="card">${li("Stop-loss", c.risk.stop)}${li("Trailing stop", c.risk.trailing)}${li("Surveillance", c.risk.surveillance)}${c.risk.time_exit ? li("Sortie temps", c.risk.time_exit) : ""}</div></div>`;
}

/* ---------- token detail ---------- */
let chart = null;
async function openToken(mint) {
  if (!mint) return;
  const t = await fetch("/api/token?mint=" + encodeURIComponent(mint)).then(r => r.json());
  const s = t.snap || {}, p = t.position, eq = t.equity || BANK;
  $("#dtitle").innerHTML = `${avatar(t.icon, t.symbol)}<span>${esc(t.symbol || "?")}</span>`;
  const capPct = p && p.status === "open" ? pct(p.cost_usd / eq * 100, false) + " du capital" : "pas de position";
  $("#dsub").innerHTML = `${esc(t.symbol)} • Solana • ${price(s.price)} • ${capPct}`;
  $("#dmetrics").innerHTML = [["Market cap", usdK(s.mcap)], ["Liquidité", usdK(s.liq)], ["Holders", t.holders ? Number(t.holders).toLocaleString("fr-FR") : "—"], ["Volume 24h", usdK((s.vol || {}).h24)]]
    .map(([a, b]) => `<div class="card"><div class="ml">${a}</div><div class="mv">${b}</div></div>`).join("");
  let cards = "";
  if (p) {
    const last = p.status === "open" ? (p.last_price || p.entry_price) : p.exit_price;
    const val = p.status === "open" ? last * p.qty : p.proceeds_usd, pnl = val - p.cost_usd;
    const exitLbl = p.exit_reason_fr || (p.exit_reason === "stop_loss" ? "stop -6 %" : p.exit_reason === "time_exit_flat" ? "sortie temps" : "trailing");
    cards += `<div class="card pcard"><div class="ph">Votre position ${p.status === "closed" ? "(clôturée · " + esc(exitLbl) + ")" : ""}${p.trigger_fr ? " · " + esc(p.trigger_fr) : ""}</div>
      <div class="pv"><div><div class="big">${usd(p.cost_usd)}</div><div class="muted small">montant investi · Executor</div></div><div style="text-align:right"><div class="big">${usd(val)}</div><div class="small ${pnl >= 0 ? "green" : "red"}">${usd(pnl, true)} (${pct(pnl / p.cost_usd * 100)})</div></div></div></div>
      <div class="card pcard"><div class="ph">Risk · trailing stop</div><div class="pv"><div><div class="small">sortie si -6 % depuis le plus haut</div><div class="muted small">${p.trail_active ? "trailing actif · pic " + price(p.peak_price) : "s'active à +12 % (" + price(p.entry_price * 1.12) + ")"}</div></div><div class="big orange">${price(p.stop_price)}</div></div></div>`;
  } else if (t.score) {
    cards += `<div class="card pcard"><div class="ph">Analyst</div><div class="big ${t.score.passed ? "green" : "orange"}">${t.score.score.toLocaleString("fr-FR")} / 100</div><div class="muted small">${t.score.passed ? "validé" : "sous le seuil de " + seuil()}</div></div>`;
  }
  if (t.kills && t.kills.length) cards += `<div class="card pcard"><div class="ph">Filter · éliminé</div>${t.kills.map(k => `<div class="small red" style="margin:4px 0">✕ ${esc(k.reason_fr)}${k.value && k.value !== "null" ? ` <span class="muted">(${esc(k.value)})</span>` : ""}</div>`).join("")}</div>`;
  if (s.url) cards += `<div class="foot-note"><a class="green" href="${esc(s.url)}" target="_blank" rel="noopener">Voir sur DexScreener</a></div>`;
  $("#dcards").innerHTML = cards;
  $("#detail").classList.add("open");
  const el = $("#candles"); el.innerHTML = "";
  if (chart) { chart.remove(); chart = null; }
  chart = LightweightCharts.createChart(el, {height: 280, layout: {background: {color: "#1C1C1E"}, textColor: "#8E8E93", fontSize: 11},
    grid: {vertLines: {visible: false}, horzLines: {color: "rgba(255,255,255,.05)"}}, rightPriceScale: {borderVisible: false}, timeScale: {borderVisible: false, timeVisible: true},
    localization: {locale: "fr-FR", priceFormatter: v => price(v)}});
  const cs = chart.addCandlestickSeries({upColor: "#32D74B", downColor: "#FF453A", borderVisible: false, wickUpColor: "#32D74B", wickDownColor: "#FF453A", priceFormat: {type: "price", precision: 10, minMove: 1e-10}});
  const o = await fetch(`/api/ohlcv?pair=${encodeURIComponent(t.pair)}&mint=${encodeURIComponent(mint)}&tf=minute&agg=5`).then(r => r.json()).catch(() => ({candles: []}));
  const tz = 3600; // display in Europe/Paris (UTC+1 en hiver)
  cs.setData((o.candles || []).map(c => ({...c, time: c.time + tz})));
  $("#csrc").textContent = o.candles && o.candles.length ? `Bougies 5 min · ${o.source === "geckoterminal" ? "GeckoTerminal" : "échantillons de prix du desk"} · heure de Paris` : "Bougies indisponibles pour ce pool";
  if (p) {
    cs.createPriceLine({price: p.entry_price, color: "#32D74B", lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "Achat Executor"});
    cs.createPriceLine({price: p.stop_price, color: "#FF453A", lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: p.trail_active ? "Trailing Risk" : "Stop Risk"});
  }
  chart.timeScale().fitContent();
}
$("#back").onclick = () => $("#detail").classList.remove("open");
document.addEventListener("click", e => { const r = e.target.closest("[data-mint]"); if (r && r.dataset.mint) openToken(r.dataset.mint); });

/* ---------- nav ---------- */
function go(tab) { document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + tab));
  document.querySelectorAll(".bnav button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab)); window.scrollTo(0, 0); location.hash = tab === "home" ? "" : tab; renderTabs(); }
document.querySelectorAll(".bnav button").forEach(b => b.onclick = () => go(b.dataset.tab));
document.querySelectorAll("[data-go]").forEach(b => b.onclick = () => go(b.dataset.go));
document.querySelectorAll("#tf button").forEach(b => b.onclick = () => { tf = b.dataset.tf; document.querySelectorAll("#tf button").forEach(x => x.classList.toggle("on", x === b)); if (D) drawEquity(D.equity); });
document.querySelectorAll("#seg button").forEach(b => b.onclick = () => { actFilter = b.dataset.f; document.querySelectorAll("#seg button").forEach(x => x.classList.toggle("on", x === b)); renderActivityTab(); });
const SETUP_FR = {obi: "Déséquilibre carnet (OBI)", flow_burst: "Rafale de flux", vwap_pullback: "Repli VWAP/EMA", bb_rsi: "Bollinger + RSI", fvg: "Fair value gap", sweep: "Liquidity sweep", order_block: "Order block", ema_scalp: "Scalp EMA 9/21", mean_rev: "Retour à la moyenne", twap_reclaim: "Reprise TWAP"};
const EXIT_FR = {take_profit: "objectif", stop: "stop", time_exit: "sortie temps"};
function lessonsHtml(rows, title) {
  if (!rows || !rows.length) return `<div class="small"><b>${title}</b></div><div class="muted small" style="margin:4px 0 10px">Pas encore assez de trades (une règle se désactive après 20 trades à espérance négative, taille ÷2 dès 10).</div>`;
  return `<div class="small"><b>${title}</b></div>` + rows.map(r => `<div class="li"><span>${esc(r.kind)} · ${esc(SETUP_FR[r.value] || r.value)} <span class="muted tiny">(${r.n} trades, ${pct(r.win_rate, false)} gagnants)</span></span><span class="${r.status === "ok" ? "green" : "red"}">${esc(r.status_fr)} · ${pct(r.expectancy_pct)}</span></div>`).join("") + '<div style="height:10px"></div>';
}
function renderIntensif() {
  const I = D.intensif || {}; const fx = I.eurusd || FX; const eur = (n, sg) => n == null ? "—" : ((n < 0 ? "-" : (sg ? "+" : "")) + fr2(Math.abs(n / fx)) + " €");
  const card = (a, b, cls) => `<div class="card"><div class="ml">${a}</div><div class="mv ${cls || ""}">${b}</div></div>`;
  $("#int-stats").innerHTML = [card("Portefeuille", eur(I.equity_usd)), card("PnL net (après frais)", eur(I.pnl_net_usd, true), (I.pnl_net_usd || 0) >= 0 ? "green" : "red"),
    card("Exécutions / min", `${I.exec_last_min ?? 0} <span class="muted small">(moy. 10 min ${String(I.exec_per_min_10m ?? 0).replace(".", ",")})</span>`),
    card("Taux de réussite", I.win_rate == null ? "—" : pct(I.win_rate, false) + ` <span class="muted small">${I.wins}/${I.closed}</span>`),
    card("Frais payés", eur(I.fees_usd)), card("Trades clos", `${I.closed ?? 0} <span class="muted small">${I.markets_live ?? 0}/${I.watch ?? 0} marchés en direct</span>`),
    card("Exposition", eur(I.exposure_usd) + ` <span class="muted small">max 20 %</span>`), card("Statut", I.paused ? '<span class="red">en pause (${esc(String(I.paused))})</span>' : `<span class="green">actif</span> <span class="muted small">jour ${pct(I.day_pct)}</span>`)].join("");
  const bs = I.by_setup || [];
  $("#int-setups").innerHTML = bs.length ? bs.map(b => `<div class="li"><span>${esc(SETUP_FR[b.setup] || b.setup)} <span class="muted tiny">${b.n} trades · ${pct(b.w / b.n * 100, false)}</span></span><span class="${b.pnl >= 0 ? "green" : "red"}">${eur(b.pnl, true)}</span></div>`).join("") : '<div class="empty">En attente des premiers signaux (préchauffage ~6 min).</div>';
  const bm = I.by_market || [];
  $("#int-markets").innerHTML = bm.length ? bm.map(b => `<div class="li"><span>${esc(b.label)} <span class="muted tiny">${esc(b.venue_fr)} · ${esc(b.asset_class)} · ${b.n} trades · ${pct(b.w / b.n * 100, false)}</span></span><span class="${b.pnl >= 0 ? "green" : "red"}">${eur(b.pnl, true)}</span></div>`).join("") : '<div class="empty">Aucun trade clos.</div>';
  const op = I.open || [];
  $("#int-open").innerHTML = op.length ? op.map(p => { const v = p.last_price / p.entry_price - 1; return `<div class="row"><div class="av">${esc((p.symbol||"?").slice(0,2).toUpperCase())}</div><div class="mid"><div class="mt">${esc(p.symbol)}</div><div class="ms">${p.side < 0 ? "vente (short)" : "achat"} · ${esc(SETUP_FR[p.setup] || p.setup)} · ${hhmm(p.entry_ts)} · mise ${eur(p.cost_usd)}</div></div><div class="rt"><div class="ra ${v * (p.side || 1) >= 0 ? "green" : "red"}">${pct(v * (p.side || 1) * 100)}</div></div></div>`; }).join("") : '<div class="empty">Aucune position</div>';
  const rc = I.recent || [];
  $("#int-recent").innerHTML = rc.length ? rc.slice(0, 25).map(t => `<div class="row"><div class="av">${esc((t.symbol||"?").slice(0,2).toUpperCase())}</div><div class="mid"><div class="mt">${esc(t.symbol)} · ${t.side < 0 ? "short" : "long"} · ${esc(SETUP_FR[t.setup] || t.setup)}</div><div class="ms">${hhmm(t.exit_ts)} · ${esc(EXIT_FR[t.exit_reason] || t.exit_reason)} · ${Math.round(t.hold_s || 0)} s · frais ${eur(t.fee_usd)}</div></div><div class="rt"><div class="ra ${t.pnl_usd >= 0 ? "green" : "red"}">${eur(t.pnl_usd, true)}</div><div class="rs">${pct(t.pnl_pct)}</div></div></div>`).join("") : '<div class="empty">Rien pour l\'instant.</div>';
  $("#lessons").innerHTML = lessonsHtml(I.lessons_fr, "Mode intensif") + lessonsHtml((D.lessons || {}).profit, "Mode profit");
  const fd = I.feeds || {};
  $("#int-foot").innerHTML = `Papier uniquement · flux : Binance spot et perps (WebSocket), Kraken spot (WebSocket), Jupiter (~2 s) · bougies 15 s et 1 min · mise 0,75 % · stop ATR 0,3–1 %, objectif 1,5× le stop · sortie après 10 min · exposition max 20 % · pause à -3 % sur la journée ou après 6 pertes de suite · frais : Binance spot 0,10 %, perps 0,02 % maker / 0,05 % taker, Kraken 0,25 / 0,40 %, DEX 0,30 % + spread et latence · ordres limite remplis seulement si le prix traverse · messages reçus : ${Object.entries(fd).map(([k, v]) => k + " " + (v.msgs || 0).toLocaleString("fr-FR")).join(", ")} · mis à jour ${hhmm(I.ts)}`;
}
function renderTabs() { if (!D) return; const a = document.querySelector(".tab.active").id; if (a === "tab-intensif") renderIntensif();
  if (a === "tab-agents") renderAgentsTab(); if (a === "tab-activity") renderActivityTab(); if (a === "tab-account") renderAccount();
  if (a === "tab-orders" && window.renderOrders) window.renderOrders(); if (a === "tab-account" && window.renderSession) window.renderSession(); }

/* ---------- main loop ---------- */
async function tick() {
  try {
    const resp = await fetch("/api/all", {cache: "no-store"});
    if (resp.status === 401) { location.href = "/login"; return; }
    D = await resp.json();
    const meta = {}; D.activity.forEach(e => { if (e.icon) meta[e.mint] = e.icon; });
    D.positions.open.forEach(p => p.icon = meta[p.mint]);
    const S = D.summary; if (S.eurusd) FX = S.eurusd; if (S.bankroll) BANK = S.bankroll; if (S.bankroll_eur) BANK_EUR = S.bankroll_eur; setBalance(S.equity);
    S.pnl_usd = (S.pnl_eur != null ? S.pnl_eur * FX : S.pnl_usd);
    if (Math.abs(S.pnl_usd) < 0.01) S.pnl_usd = 0;
    if (Math.abs(S.pnl_pct) < 0.005) S.pnl_pct = 0;
    const up = S.pnl_usd >= 0;
    $("#delta").className = "delta " + (up ? "up" : "down"); $("#delta").textContent = `${up ? "⬆" : "⬇"} ${usd(Math.abs(S.pnl_usd))} (${pct(Math.abs(S.pnl_pct), false)})`;
    const m = $("#mult"); m.textContent = ((S.equity_eur ?? S.equity / FX) / BANK_EUR).toLocaleString("fr-FR", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + "x"; m.className = "pill-mult" + (up ? "" : " down");
    setModeBadges();
    const sl = $("#seuil-lbl"); if (sl) sl.textContent = "seuil " + seuil();
    drawEquity(D.equity); agentCards(); renderActivity(); checkToasts(D.activity); renderTabs();
    $("#foot").innerHTML = `Mode papier · ${esc(profileLabel())} · capital virtuel ${fr2(BANK_EUR)} € (1 € = ${Number(FX).toLocaleString("fr-FR",{maximumFractionDigits:4})} $) · données DexScreener, RugCheck, GeckoTerminal<br>cycle ${S.cycle ?? 0} · mis à jour ${hhmm(S.ts)} (heure de Paris)`;
  } catch (e) { console.error(e); }
}
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
tick(); setInterval(tick, 4000);
if (location.hash.slice(1)) go(location.hash.slice(1));
const qm = new URLSearchParams(location.search).get("token"); if (qm) setTimeout(() => openToken(qm), 800);
