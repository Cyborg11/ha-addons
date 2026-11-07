"use strict";
const $ = id => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};
let token = store.get("pcc_ui_token") || "";
let ws, retry = 1000, wakeLock = null, tab = store.get("pcc_tab") || "dash";
const HIST = 120; // Sekunden Verlauf
const hist = { gpu: [], temp: [], cpu: [], ram: [], down: [], up: [] };
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const CIRC = 276.46;

/* ---------------- Ansichten ---------------- */
function show(view) {
  for (const id of ["login", "offline", "waking", "live"]) $(id).hidden = id !== view;
  $("tabs").hidden = view !== "live";
  document.body.classList.toggle("is-live", view === "live");
}

function showTab(name) {
  tab = ["dash", "ctrl", "files"].includes(name) ? name : "dash";
  store.set("pcc_tab", tab);
  document.querySelectorAll(".view").forEach(v => { v.hidden = v.dataset.view !== tab; });
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  if (tab === "dash") drawAll();
}
document.querySelectorAll("#tabs button").forEach(b => { b.onclick = () => showTab(b.dataset.tab); });

/* ---------------- Formatierung ---------------- */
const n = (v, unit = "") => (v === null || v === undefined ? "–" : v + unit);
const gb = mb => (mb === null || mb === undefined ? "–" : (mb / 1024).toFixed(1));
function rate(kbps) {
  kbps = kbps || 0;
  return kbps >= 1000 ? (kbps / 1000).toFixed(1) + " Mbit/s" : Math.round(kbps) + " kbit/s";
}
function level(v, warn, crit) { return v >= crit ? "crit" : v >= warn ? "warn" : "ok"; }

/* ---------------- Ringe & Balken ---------------- */
function setRing(key, frac, text, lv) {
  const el = document.querySelector(`.ring[data-k="${key}"]`);
  const f = Math.max(0, Math.min(1, frac || 0));
  el.querySelector(".fg").style.strokeDashoffset = CIRC * (1 - f);
  el.classList.remove("lv-warn", "lv-crit");
  if (lv !== "ok") el.classList.add("lv-" + lv);
  el.querySelector("b").textContent = text;
}

function setBar(id, frac, lv) {
  const el = $(id);
  el.style.width = Math.max(0, Math.min(1, frac || 0)) * 100 + "%";
  el.style.setProperty("--b", `var(--${lv || "ok"})`);
}

/* ---------------- Verlaufsgrafiken ---------------- */
function spark(id, series, colors, max) {
  const cv = $(id);
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) { const y = Math.round(h * i / 4) + .5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  const top = max || Math.max(1, ...series.flat()) * 1.2;
  series.forEach((arr, si) => {
    if (arr.length < 2) return;
    const pts = arr.map((v, i) => [w * (i + HIST - arr.length) / (HIST - 1), h - 4 - Math.min(v / top, 1) * (h - 8)]);
    const col = css(colors[si]);
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
    if (si === 0) {
      ctx.lineTo(pts[pts.length - 1][0], h); ctx.lineTo(pts[0][0], h); ctx.closePath();
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, col + "55"); g.addColorStop(1, col + "00");
      ctx.fillStyle = g; ctx.fill();
    }
  });
}

function drawAll() {
  spark("g_gpu", [hist.gpu, hist.temp], ["--gpu", "--temp"], 100);
  spark("g_cpu", [hist.cpu], ["--cpu"], 100);
  spark("g_ram", [hist.ram], ["--ram"], 100);
  spark("g_net", [hist.down, hist.up], ["--net", "--disk"]);
}

function push(key, v) {
  const a = hist[key];
  a.push(v || 0);
  if (a.length > HIST) a.shift();
}

/* ---------------- Rendern ---------------- */
let coreEls = [];
function renderCores(list) {
  const box = $("cores");
  if (coreEls.length !== list.length) {
    box.innerHTML = "";
    coreEls = list.map(() => box.appendChild(document.createElement("i")));
  }
  list.forEach((v, i) => { coreEls[i].style.height = Math.max(6, v) + "%"; });
}

function renderDisks(disks) {
  const box = $("disks");
  if (box.children.length !== disks.length) {
    box.innerHTML = disks.map((d, i) =>
      `<div class="disk"><div class="mh"><span>${d.mount}</span><b id="dv${i}"></b></div><div class="bar"><i id="db${i}"></i></div></div>`).join("");
  }
  disks.forEach((d, i) => {
    $("dv" + i).textContent = d.used_pct + " %";
    setBar("db" + i, d.used_pct / 100, level(d.used_pct, 85, 95));
  });
}

function render(s) {
  const g = s.gpu || {}, c = s.cpu || {}, r = s.ram || {}, net = s.net || {};
  $("host").textContent = s.host || "PC";
  const u = s.uptime_s || 0;
  $("sub").textContent = "Uptime " + (u >= 86400 ? Math.floor(u / 86400) + " d " : "") + Math.floor((u % 86400) / 3600) + " h " + Math.floor((u % 3600) / 60) + " min";

  setRing("gpu_temp", (g.temp_c || 0) / 100, n(g.temp_c), level(g.temp_c || 0, 70, 82));
  $("rs_temp").textContent = g.fan_pct != null ? "Lüfter " + g.fan_pct + " %" : "";
  setRing("gpu_util", (g.util_pct || 0) / 100, n(g.util_pct), level(g.util_pct || 0, 90, 101));
  $("rs_util").textContent = g.clock_mhz != null ? g.clock_mhz + " MHz" : "";
  const vf = g.vram_total_mb ? g.vram_used_mb / g.vram_total_mb : 0;
  setRing("vram", vf, g.vram_total_mb ? Math.round(vf * 100) : "–", level(vf * 100, 85, 95));
  $("rs_vram").textContent = g.vram_total_mb ? gb(g.vram_used_mb) + " / " + gb(g.vram_total_mb) + " GB" : "";

  $("gpu_name").textContent = (g.name || "").replace("NVIDIA GeForce ", "");
  const pf = g.power_limit_w ? (g.power_w || 0) / g.power_limit_w : 0;
  $("t_power").textContent = n(g.power_w, " W") + (g.power_limit_w ? " / " + g.power_limit_w + " W" : "");
  setBar("bar_power", pf, level(pf * 100, 85, 98));
  $("gpu_clock").textContent = n(g.clock_mhz, " MHz");
  $("gpu_fan").textContent = n(g.fan_pct, " %");

  $("cpu_val").textContent = n(c.util_pct != null ? Math.round(c.util_pct) : null);
  $("cpu_freq").textContent = c.freq_mhz != null ? (c.freq_mhz / 1000).toFixed(2) + " GHz" : "–";
  $("cpu_temp").textContent = n(c.temp_c, " °C");
  renderCores(c.per_core_pct || []);

  const rf = r.total_mb ? r.used_mb / r.total_mb : 0;
  $("ram_val").textContent = gb(r.used_mb);
  $("ram_of").textContent = "/ " + gb(r.total_mb) + " GB";
  setBar("bar_ram", rf, level(rf * 100, 85, 95));

  $("net_down").textContent = rate(net.down_kbps);
  $("net_up").textContent = rate(net.up_kbps);
  renderDisks(s.disks || []);

  push("gpu", g.util_pct); push("temp", g.temp_c); push("cpu", c.util_pct);
  push("ram", rf * 100); push("down", net.down_kbps); push("up", net.up_kbps);
  if (tab === "dash") drawAll();
}

/* ---------------- Verbindung ---------------- */
function onMessage(m) {
  window.dispatchEvent(new CustomEvent("pcc:status", { detail: m.status }));
  const badge = $("badge");
  badge.textContent = { online: "online", offline: "offline", waking: "startet" }[m.status] || m.status;
  badge.className = "badge " + m.status;
  $("warn").hidden = m.api_ok;
  if (m.status === "online") {
    if ($("live").hidden) { show("live"); showTab(tab); }
    if (m.snapshot) render(m.snapshot);
  } else if (m.status === "waking") {
    show("waking");
    $("host").textContent = m.host || "PC-Companion";
    $("sub").textContent = "";
    $("countdown").textContent = "noch bis zu " + (m.waking_left ?? "?") + " s";
  } else {
    show("offline");
    $("host").textContent = m.host || "PC-Companion";
    $("sub").textContent = "";
    $("wake").disabled = !m.wol_configured;
    if (!m.wol_configured) $("wakemsg").textContent = "pc_mac im Add-on nicht konfiguriert.";
    for (const k in hist) hist[k].length = 0;
  }
}

function connect() {
  if (!token) { askToken(""); return; }
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const base = location.pathname.replace(/[^/]*$/, "");
  ws = new WebSocket(proto + location.host + base + "ws?token=" + encodeURIComponent(token));
  let opened = false;
  ws.onopen = () => { opened = true; retry = 1000; };
  ws.onmessage = e => onMessage(JSON.parse(e.data));
  ws.onclose = async () => {
    // Der Hub lehnt falsche Tokens schon beim Handshake ab (HTTP 403) – der Browser meldet dann
    // nur Code 1006. Deshalb per REST prüfen, ob das Token abgelehnt wurde.
    if (!opened) {
      try {
        const r = await fetch("api/status", { headers: { Authorization: "Bearer " + token } });
        if (r.status === 401) { askToken("Token falsch oder im Add-on (ui_token) nicht gesetzt."); return; }
      } catch (e) { /* Hub nicht erreichbar */ }
    }
    $("badge").textContent = "Hub getrennt"; $("badge").className = "badge offline";
    setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
  };
}

function askToken(msg) {
  token = ""; store.set("pcc_ui_token", "");
  $("loginmsg").textContent = msg || "";
  $("badge").textContent = "Token nötig"; $("badge").className = "badge offline";
  show("login");
}
$("badge").onclick = () => { if (ws) { ws.onclose = null; ws.close(); } askToken("Neues Token eingeben."); };

$("save").onclick = () => { token = $("token").value.trim(); store.set("pcc_ui_token", token); connect(); };
$("wake").onclick = async () => {
  $("wakemsg").textContent = "Sende Magic Packet …";
  try {
    const r = await fetch("api/wake", { method: "POST", headers: { Authorization: "Bearer " + token } });
    $("wakemsg").textContent = r.ok ? "" : "Fehler: " + (await r.json()).detail;
  } catch (e) { $("wakemsg").textContent = "Hub nicht erreichbar"; }
};

/* ---------------- Display-Helfer ---------------- */
$("lock").onclick = async () => {
  try {
    if (wakeLock) { await wakeLock.release(); wakeLock = null; $("lock").classList.remove("on"); return; }
    wakeLock = await navigator.wakeLock.request("screen");
    wakeLock.addEventListener("release", () => { wakeLock = null; $("lock").classList.remove("on"); });
    $("lock").classList.add("on");
  } catch (e) { $("lock").title = "Wake Lock nicht verfügbar"; }
};
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && $("lock").classList.contains("on") && !wakeLock)
    navigator.wakeLock.request("screen").then(l => { wakeLock = l; }).catch(() => {});
});
$("full").onclick = () => {
  try {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  } catch (e) { /* nicht unterstützt */ }
};
if (!document.documentElement.requestFullscreen) $("full").hidden = true;
window.addEventListener("resize", () => { if (tab === "dash" && !$("live").hidden) drawAll(); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
show("login"); $("login").hidden = true; // bis zur ersten Statusmeldung nichts anzeigen
connect();
