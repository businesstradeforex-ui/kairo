"use strict";
const csrf = (document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/) || [])[1] || "";
async function api(url, body) {
  const r = await fetch(url, {method: body ? "POST" : "GET", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 403 || r.status === 401) { location.href = "/"; return {}; }
  return r.json();
}
async function load() {
  const s = await api("/api/owner/state");
  const el = document.getElementById("state");
  if (!el) return;
  el.textContent = JSON.stringify({profil: s.ai && s.ai.profile, pause: s.ai && s.ai.desk_paused, equity: s.summary && s.summary.equity_eur}, null, 2);
  const t = await api("/api/owner/tokens");
  document.getElementById("tokens").innerHTML = (t.tokens || []).map(x => `<div class="li"><span>${x.name} · ${x.prefix}… · ${x.scopes}${x.revoked ? " · révoqué" : ""}</span><button data-id="${x.id}" class="rev" type="button">révoquer</button></div>`).join("");
}
document.getElementById("tok").onsubmit = async (e) => {
  e.preventDefault();
  const out = await api("/api/owner/token", {name: document.getElementById("tname").value || "assistant", scopes: ["read", "params", "orders", "ui"]});
  document.getElementById("once").textContent = out.token ? ("Copiez-le maintenant :\n" + out.token) : (out.error || "");
  load();
};
document.getElementById("tokens").onclick = async (e) => {
  const id = e.target && e.target.dataset && e.target.dataset.id;
  if (!id) return;
  await api("/api/owner/token/revoke", {id: Number(id)});
  load();
};
load();
