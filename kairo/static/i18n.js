"use strict";
const I18N = {
  fr: {brand:"Kairo", tag:"Desk memecoins Solana", agents:"Agents", activity:"Activité", intensif:"Mode intensif", account:"Compte", orders:"Ordres",
       nav_home:"Accueil", nav_agents:"Agents", nav_activity:"Activité", nav_intensif:"Intensif", nav_orders:"Ordres", nav_account:"Compte"},
  en: {brand:"Kairo", tag:"Solana memecoin desk", agents:"Agents", activity:"Activity", intensif:"Intensive", account:"Account", orders:"Orders",
       nav_home:"Home", nav_agents:"Agents", nav_activity:"Activity", nav_intensif:"Intensive", nav_orders:"Orders", nav_account:"Account"}
};
function kairoLang() { return localStorage.getItem("kairo_lang") === "en" ? "en" : "fr"; }
function applyLang() {
  const lang = kairoLang();
  document.documentElement.lang = lang;
  const dict = I18N[lang];
  document.querySelectorAll("[data-i18n]").forEach(el => { const k = el.dataset.i18n; if (dict[k]) el.textContent = dict[k]; });
  const nav = ["home","agents","activity","intensif","orders","account"];
  document.querySelectorAll(".bnav button").forEach(b => { const t = dict["nav_" + b.dataset.tab]; if (t) { const ic = b.querySelector("span"); b.innerHTML = ""; if (ic) b.appendChild(ic); b.append(t); } });
  const btn = document.getElementById("lang-toggle");
  if (btn) btn.textContent = lang === "fr" ? "EN" : "FR";
}
document.addEventListener("click", e => {
  if (e.target && e.target.id === "lang-toggle") {
    localStorage.setItem("kairo_lang", kairoLang() === "fr" ? "en" : "fr");
    applyLang();
  }
});
applyLang();
