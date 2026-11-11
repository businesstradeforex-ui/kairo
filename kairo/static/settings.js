"use strict";
function csrfToken() { return (document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/) || [])[1] || ""; }
async function api(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken()}, body: JSON.stringify(body || {})});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "erreur");
  return data;
}
async function renderSettings(force) {
  const box = document.getElementById("settings");
  if (!box || (box.dataset.ready === "1" && !force)) return;
  let s;
  try { s = await fetch("/api/settings", {cache: "no-store"}).then(r => r.json()); } catch (e) { return; }
  const u = s.user || {};
  const live = s.live || {};
  const conns = await fetch("/api/connectors", {cache: "no-store"}).then(r => r.json()).catch(() => ({connectors: []}));
  const linked = (conns.connectors || []).map(c => `<div class="li"><span>${esc(c.label_fr || c.kind)}</span><span>${esc((c.public && (c.public.address || c.public.key_last4)) || "relié")}</span></div>`).join("");
  box.innerHTML = `<div class="acc">
    <h3>Papier</h3>
    <div class="card">
      <label class="muted small">Capital de départ (€)</label>
      <input id="paper-eur" value="${esc(u.paper_eur || 1000)}" inputmode="decimal" style="width:100%;margin:8px 0;background:#2C2C2E;border:0;border-radius:12px;color:#fff;padding:12px;font-size:16px">
      <button class="btn-out" id="paper-save" style="color:#32D74B" type="button">Enregistrer le capital</button>
      <button class="btn-out" id="paper-reset" type="button">Remettre à zéro…</button>
    </div>
    <h3>Comptes connectés</h3>
    <div class="card">${linked || '<div class="empty">Aucun compte relié</div>'}
      <button class="btn-out" id="link-phantom" style="color:#32D74B" type="button">Relier Phantom (adresse publique)</button>
      <button class="btn-out" id="link-kraken" style="color:#fff" type="button">Relier Kraken (clé sans retrait)</button>
      <p class="muted tiny">Phantom et Solflare : adresse seulement, jamais de clé privée. Kraken, Binance, Coinbase : secret chiffré. Jupiter : cotations, sans clé. Les vrais ordres restent désactivés.</p>
    </div>
    <h3>Trading réel</h3>
    <div class="card">
      <div class="li"><span>Serveur</span><span>${live.server_enabled ? "autorisé" : "coupé"}</span></div>
      <div class="li"><span>Ce compte</span><span>${live.account_enabled ? "opt-in" : "papier seulement"}</span></div>
      <div class="li"><span>Plafond / ordre</span><span>${esc(live.max_order)} $ (dur ${esc(live.hard_order)} $)</span></div>
      <button class="btn-out" id="live-on" type="button">${live.account_enabled ? "Désactiver le réel" : "Activer le réel…"}</button>
      <button class="btn-out" id="kill" type="button">Kill switch</button>
    </div>
    <h3>Sécurité du compte</h3>
    <div class="card">
      <div class="li"><span>2FA</span><span>${u.totp_enabled ? "actif" : "inactif"}</span></div>
      <button class="btn-out" id="totp" style="color:#32D74B" type="button">${u.totp_enabled ? "Désactiver 2FA" : "Activer 2FA"}</button>
      ${u.is_owner ? '<a class="btn-out" style="display:block;text-align:center;text-decoration:none;color:#fff" href="/admin">Espace propriétaire</a>' : ""}
    </div>
  </div>`;
  box.dataset.ready = "1";
  const refresh = () => { box.dataset.ready = ""; renderSettings(true); };
  $("#paper-save").onclick = async () => { try { await api("/api/paper/capital", {eur: $("#paper-eur").value}); toast("Capital papier mis à jour"); } catch (e) { toast(esc(e.message)); } };
  $("#paper-reset").onclick = async () => {
    if (!confirm("Effacer toutes les positions papier et repartir du capital indiqué ?")) return;
    try { await api("/api/paper/reset", {confirm: "RESET", eur: $("#paper-eur").value}); toast("Compte papier remis à zéro"); } catch (e) { toast(esc(e.message)); }
  };
  $("#link-phantom").onclick = async () => {
    const provider = (window.phantom && window.phantom.solana) || window.solana;
    let address = "";
    if (provider) { const c = await provider.connect(); address = c.publicKey.toString(); }
    else address = prompt("Adresse publique Phantom (pas de clé privée)") || "";
    if (!address) return;
    try { await api("/api/connectors", {kind: "phantom", address}); toast("Phantom relié"); refresh(); } catch (e) { toast(esc(e.message)); }
  };
  $("#link-kraken").onclick = async () => {
    const api_key = prompt("Clé API Kraken (sans permission de retrait)");
    const api_secret = prompt("Secret API Kraken");
    if (!api_key || !api_secret) return;
    try { await api("/api/connectors", {kind: "kraken", api_key, api_secret}); toast("Kraken relié, secret chiffré"); refresh(); } catch (e) { toast(esc(e.message)); }
  };
  $("#live-on").onclick = async () => {
    const enabled = !live.account_enabled;
    try {
      await api("/api/live/opt-in", enabled ? {enabled: true, confirm: "LIVE"} : {enabled: false});
      toast(enabled ? "Opt-in enregistré. Chaque ordre réel demandera CONFIRMER." : "Retour au papier");
      refresh();
    } catch (e) { toast(esc(e.message)); }
  };
  $("#kill").onclick = async () => { try { await api("/api/kill-switch", {on: true, global: !!u.is_owner}); toast("Kill switch actif"); } catch (e) { toast(esc(e.message)); } };
  $("#totp").onclick = async () => {
    try {
      if (u.totp_enabled) {
        const code = prompt("Code actuel pour désactiver");
        await api("/api/account/totp/disable", {code});
      } else {
        const setup = await api("/api/account/totp/setup", {});
        prompt("Ajoutez ce secret dans votre application (ou l'URI)", setup.otpauth);
        const code = prompt("Code à 6 chiffres pour confirmer");
        await api("/api/account/totp/enable", {code});
      }
      refresh();
    } catch (e) { toast(esc(e.message)); }
  };
}
const _prevTabs = window.renderTabs;
window.renderTabs = function () { if (_prevTabs) _prevTabs(); if (document.querySelector(".tab.active") && document.querySelector(".tab.active").id === "tab-account") renderSettings(); };
