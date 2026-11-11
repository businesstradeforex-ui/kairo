"use strict";
/* Version web : panneau « Ordres & IA locale » + session (déconnexion). Utilise $, esc, hhmm de app.js. */
(() => {
  let ME = null, O = null, busy = false;
  const ACT_FR = {set_profile: "Profil", set_intensif: "Mode intensif", set_param: "Paramètre", reset_params: "Réinitialisation",
    pause_desk: "Pause du desk", resume_desk: "Reprise du desk", summary: "Résumé", order_received: "Ordre reçu", login: "Connexion",
    update_ui: "Mise à jour de l'interface", "/api/orders": "Ordre", "/api/update-ui": "Mise à jour UI", "?": "Ordre"};
  const OUT_FR = {executed: ["exécuté", "green"], refused: ["refusé", "red"], error: ["erreur", "red"], queued: ["en file", "muted"], failed: ["échec", "red"]};
  const SRC_FR = {web: "vous", grokbot: "assistant"};
  const CHIPS = ["Résumé des 6 dernières heures", "Passe en mode profit", "Pause", "Reprends", "Liquidité min 20k", "Max 6 positions", "Coupe l'intensif", "Relance l'intensif"];

  async function me() {
    try { const r = await fetch("/api/me", {cache: "no-store"}); if (r.status === 401) { location.href = "/login"; return null; } ME = await r.json(); } catch (e) {}
    return ME;
  }
  async function load() {
    try { const r = await fetch("/api/orders?limit=40", {cache: "no-store"}); if (r.ok) O = await r.json(); } catch (e) {}
  }
  function statusHtml(s) {
    if (!s) return "";
    const li = (a, b) => `<div class="li"><span>${a}</span><span>${b}</span></div>`;
    const ov = Object.entries(s.overrides || {});
    return li("IA locale (Ollama)", s.ollama ? `<span class="green">en ligne</span> · ${esc(s.model)}${s.model_present ? "" : ' <span class="red">(modèle absent)</span>'}` : '<span class="orange">hors ligne</span> · ordres JSON et règles simples')
      + li("Profil du compte de base", esc(s.profile)) + li("Desk", s.desk_paused ? '<span class="red">en pause</span>' : '<span class="green">actif</span>')
      + li("Mode intensif", s.intensif_enabled ? '<span class="green">activé</span>' : '<span class="red">arrêté</span>')
      + li("Paramètres modifiés", ov.length ? ov.map(([k, v]) => `${esc(k)} = ${esc(v)}`).join(" · ") : "aucun (valeurs du profil)");
  }
  function chatHtml(orders) {
    if (!orders || !orders.length) return `<div class="empty">Donnez un ordre en français, par exemple « passe en mode profit ». L'IA locale le traduit en une action autorisée.</div>`;
    return orders.slice().reverse().map(o => {
      const who = SRC_FR[o.source] || o.source, t = hhmm(o.ts);
      const st = o.status === "pending" || o.status === "running";
      const res = st ? "traitement par l'IA locale…" : (o.result || "");
      return `<div class="bub me">${esc(o.raw)}<span class="meta">${esc(who)}${o.actor && o.source === "web" ? " (" + esc(o.actor) + ")" : ""} · ${t}</span></div>
        <div class="bub ai ${o.status === "refused" || o.status === "error" ? "refused" : ""} ${st ? "pending" : ""}">${o.status === "refused" ? "Refusé : " : ""}${esc(res)}<span class="meta">${esc(o.model || "")}${o.done_ts ? " · " + hhmm(o.done_ts) : ""}</span></div>`;
    }).join("");
  }
  function auditHtml(rows) {
    if (!rows || !rows.length) return `<div class="empty">Aucune action pour l'instant.</div>`;
    return rows.slice(0, 40).map(a => { const [lbl, cls] = OUT_FR[a.outcome] || [a.outcome, "muted"];
      return `<div class="row" style="cursor:default"><div class="av">${a.source === "grokbot" ? "🤖" : "👤"}</div><div class="mid"><div class="mt">${esc(ACT_FR[a.action] || a.action)}</div><div class="ms">${esc(SRC_FR[a.source] || a.source)} · ${esc(a.detail || a.params || "")}</div></div><div class="rt"><div class="ra ${cls}" style="font-size:13px">${esc(lbl)}</div><div class="rs">${hhmm(a.ts)}</div></div></div>`; }).join("");
  }
  async function renderOrders() {
    if (!ME) await me();
    await load(); if (!O) return;
    const admin = ME && ME.can_order;
    $("#ai-state").innerHTML = O.status.ollama ? '<span class="green">IA locale en ligne</span>' : '<span class="muted">IA locale hors ligne</span>';
    const sh = statusHtml(O.status); if ($("#ai-status")._h !== sh) { $("#ai-status")._h = sh; $("#ai-status").innerHTML = sh; }
    const ch = chatHtml(O.orders), c = $("#chat");
    if (c._h !== ch) { const atBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 40 || !c._h; c._h = ch; c.innerHTML = ch; if (atBottom) c.scrollTop = c.scrollHeight; }
    const ah = auditHtml(O.audit); if ($("#audit")._h !== ah) { $("#audit")._h = ah; $("#audit").innerHTML = ah; }
    $("#order-form").style.display = admin ? "" : "none";
    $("#order-chips").innerHTML = admin ? CHIPS.map(t => `<button type="button">${esc(t)}</button>`).join("") : `<div class="muted small">Compte en lecture seule : seuls les comptes admin peuvent donner des ordres.</div>`;
  }
  async function send(text) {
    text = (text || "").trim(); if (!text || busy) return;
    busy = true; $("#order-send").disabled = true;
    try {
      const r = await fetch("/api/orders?wait=20", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": (document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/) || [])[1] || ""}, body: JSON.stringify({order: text})});
      if (r.status === 401) { location.href = "/login"; return; }
      const d = await r.json().catch(() => ({}));
      if (typeof toast === "function") toast(d.status === "done" ? esc(d.result || "ordre exécuté") : d.status === "refused" ? `<span class="red">Refusé : ${esc(d.result || "")}</span>` : esc(d.error || "ordre en file d'attente"));
      $("#order-input").value = "";
    } catch (e) { console.error(e); }
    finally { busy = false; $("#order-send").disabled = false; renderOrders(); }
  }
  function renderSession() {
    const role = !ME ? "" : ME.is_owner ? "propriétaire" : ME.can_order ? "compte" : "lecture seule";
    const csrf = (document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/) || [])[1] || "";
    const h = `<div class="card" style="margin-top:14px"><div class="li"><span>Connecté en tant que</span><span>${esc(ME ? ME.username : "—")} <span class="muted small">(${esc(role)})</span></span></div></div>
      <form method="post" action="/logout"><input type="hidden" name="csrf" value="${esc(csrf)}"><button class="btn-out" type="submit">Se déconnecter</button></form>`;
    const b = $("#session-box"); if (b._h !== h) { b._h = h; b.innerHTML = h; }
  }
  $("#order-form").addEventListener("submit", e => { e.preventDefault(); send($("#order-input").value); });
  $("#order-chips").addEventListener("click", e => { const b = e.target.closest("button"); if (b) send(b.textContent); });
  window.renderOrders = renderOrders;
  window.renderSession = () => { if (ME) renderSession(); else me().then(renderSession); };
  me();
})();
