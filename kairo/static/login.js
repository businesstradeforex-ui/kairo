"use strict";
const $ = (s) => document.querySelector(s);
let mode = location.pathname === "/signup" ? "signup" : "login";
let providers = {password: true};
function csrf() {
  const m = document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}
function field(id, label, type, ac) {
  return `<label for="${id}">${label}</label><input id="${id}" name="${id}" type="${type}" autocomplete="${ac}" required>`;
}
function render() {
  const signup = mode === "signup";
  $("#go").textContent = signup ? "Créer le compte" : "Se connecter";
  $("#mode").textContent = signup ? "J'ai déjà un compte" : "Créer un compte";
  let html = signup ? field("email", "E-mail", "email", "email") + field("username", "Identifiant", "text", "username") : field("username", "E-mail ou identifiant", "text", "username");
  html += field("password", "Mot de passe", "password", signup ? "new-password" : "current-password");
  if (!signup) html += `<label for="code">Code 2FA (si activé)</label><input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="optionnel">`;
  $("#fields").innerHTML = html;
  const bits = [];
  if (!signup && providers.magic) bits.push(`<button type="button" class="alt" id="magic">Lien magique par e-mail</button>`);
  if (providers.google) bits.push(`<a class="alt" href="/auth/google">Continuer avec Google</a>`);
  if (providers.apple) bits.push(`<a class="alt" href="/auth/apple">Continuer avec Apple</a>`);
  if (providers.siws) bits.push(`<button type="button" class="alt" id="phantom">Sign in with Solana · Phantom</button>`);
  $("#providers").innerHTML = bits.join("");
  const p = $("#phantom"); if (p) p.onclick = siws;
  const m = $("#magic"); if (m) m.onclick = magic;
}
async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf()}, body: JSON.stringify(body)});
  const data = await r.json().catch(() => ({}));
  if (!r.ok && !data.totp_required) throw new Error(data.error || "erreur");
  return data;
}
$("#form").onsubmit = async (e) => {
  e.preventDefault();
  $("#err").innerHTML = "";
  const body = {csrf: csrf()};
  for (const el of $("#form").querySelectorAll("input")) body[el.name] = el.value;
  try {
    const data = await post(mode === "signup" ? "/signup" : "/login", body);
    if (data.totp_required) {
      const code = prompt("Code à 6 chiffres");
      if (!code) return;
      await post("/login/totp", {pending: data.pending, code, csrf: csrf()});
    }
    location.href = "/";
  } catch (err) { $("#err").innerHTML = `<div class="err">${err.message}</div>`; }
};
$("#mode").onclick = () => { mode = mode === "login" ? "signup" : "login"; history.replaceState(null, "", mode === "signup" ? "/signup" : "/login"); render(); };
async function magic() {
  const email = prompt("E-mail");
  if (!email) return;
  try { await post("/auth/magic", {email, csrf: csrf()}); $("#err").innerHTML = `<div class="err" style="color:#32D74B;background:rgba(50,215,75,.12)">Regardez votre boîte mail.</div>`; }
  catch (err) { $("#err").innerHTML = `<div class="err">${err.message}</div>`; }
}
async function siws() {
  const provider = (window.phantom && window.phantom.solana) || window.solana;
  if (!provider) { $("#err").innerHTML = `<div class="err">Ouvrez Kairo dans Phantom, ou installez l'extension.</div>`; return; }
  const conn = await provider.connect();
  const address = conn.publicKey.toString();
  const nonce = await post("/auth/siws/nonce", {address, csrf: csrf()});
  const encoded = new TextEncoder().encode(nonce.message);
  const signed = await provider.signMessage(encoded, "utf8");
  const sigBytes = signed.signature || signed;
  const alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  function b58(bytes) {
    let n = 0n; for (const b of bytes) n = n * 256n + BigInt(b);
    let s = ""; while (n > 0n) { s = alphabet[Number(n % 58n)] + s; n /= 58n; }
    for (const b of bytes) { if (b === 0) s = "1" + s; else break; }
    return s;
  }
  await post("/auth/siws/verify", {address, message: nonce.message, signature: b58(sigBytes), csrf: csrf()});
  location.href = "/";
}
fetch("/api/auth/providers").then(r => r.json()).then(p => { providers = p; render(); }).catch(() => render());
