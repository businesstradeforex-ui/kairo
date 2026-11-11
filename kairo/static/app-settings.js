"use strict";
function csrf() {
  const m = document.cookie.match(/(?:^|; )kairo_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : "";
}
async function api(url, body) {
  const r = await fetch(url, {method: body ? "POST" : "GET", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf()}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
const ids = {background: "background", launch_at_login: "login", notifications: "notes"};
api("/api/local/prefs").then(p => {
  document.getElementById("background").checked = !!p.background;
  document.getElementById("login").checked = !!p.launch_at_login;
  document.getElementById("notes").checked = p.notifications !== false;
});
document.getElementById("f").onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    background: document.getElementById("background").checked,
    launch_at_login: document.getElementById("login").checked,
    notifications: document.getElementById("notes").checked,
  };
  const out = await api("/api/local/prefs", body);
  document.getElementById("msg").textContent = out.ok ? "Enregistré." : (out.error || "");
};
