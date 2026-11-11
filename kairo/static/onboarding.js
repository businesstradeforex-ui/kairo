"use strict";
function csrf() {
  const m = document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}
async function api(url, body) {
  const r = await fetch(url, {method: body ? "POST" : "GET", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf()}, body: body ? JSON.stringify(body) : undefined});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "erreur");
  return data;
}
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
let poll;
function render(s) {
  const a = s.advice || {};
  const models = (a.models || []).map(m => `<div class="muted" style="margin:6px 0"><b style="color:#fff">${esc(m.id)}</b> · ${esc(m.state)} · ${esc(m.why_fr)}</div>`).join("");
  const rec = a.recommended;
  const installed = (s.models || []).map(esc).join(", ") || "aucun";
  document.getElementById("card").innerHTML = `
    <h2>IA locale</h2>
    <p class="muted">RAM ${esc(s.ram_gb)} Go · disque libre ${esc(s.free_disk_gb)} Go · Ollama ${s.ollama ? "détecté" : "absent"}.</p>
    <p class="muted">Modèles installés : ${installed}.</p>
    <p>${esc(a.reason_fr || "")}</p>
    ${rec ? `<button class="primary" id="go" type="button">${a.action === "download" ? "Télécharger " + esc(rec) : "Utiliser " + esc(rec)}</button>` : ""}
    <div class="bar"><i id="bar"></i></div>
    <p class="muted" id="prog"></p>
    <button class="ghost" id="skip" type="button">Continuer sans télécharger</button>
    <div style="margin-top:14px">${models}</div>
    <p class="muted">Trading réel éteint. Les décisions restent dans le code des agents.</p>`;
  const go = document.getElementById("go");
  if (go) go.onclick = () => act(a);
  document.getElementById("skip").onclick = skip;
}
async function act(a) {
  if (a.action === "use_installed") {
    await api("/api/local/use", {model: a.recommended});
    await test(a.recommended);
    return;
  }
  await api("/api/local/pull", {model: a.recommended});
  poll = setInterval(async () => {
    const s = await api("/api/local/status");
    const p = s.pull || {};
    const pct = p.total ? Math.min(100, Math.round(p.completed / p.total * 100)) : (p.done ? 100 : 8);
    const bar = document.getElementById("bar");
    if (bar) bar.style.width = pct + "%";
    const prog = document.getElementById("prog");
    if (prog) prog.textContent = (p.status || "") + (p.error ? " · " + p.error : "");
    if (p.done && !p.error) {
      clearInterval(poll);
      await api("/api/local/use", {model: a.recommended});
      await test(a.recommended);
    }
    if (p.done && p.error) clearInterval(poll);
  }, 700);
}
async function test(model) {
  const prog = document.getElementById("prog");
  if (prog) prog.textContent = "Test de connexion…";
  try {
    const t = await api("/api/local/test", {model});
    if (prog) prog.textContent = t.ok ? "Connexion OK." : "Le modèle n'a pas répondu.";
  } catch (e) {
    if (prog) prog.textContent = e.message;
  }
  setTimeout(() => location.href = "/login", 700);
}
async function skip() {
  await api("/api/local/prefs", {onboarding_done: true});
  location.href = "/login";
}
api("/api/local/status").then(render).catch(e => { document.getElementById("card").textContent = e.message; });
