"use strict";
const $ = id => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};
let token = store.get("pcc_ui_token") || "";
let ws, retry = 1000, wakeLock = null;
const hist = { gpu: [], cpu: [], temp: [] };

function show(view) {
  for (const id of ["login", "offline", "waking", "live"]) $(id).hidden = id !== view;
}

function setRing(key, frac, text, warn) {
  const el = document.querySelector(`.ring[data-k="${key}"]`);
  const f = Math.max(0, Math.min(1, frac || 0));
  const fg = el.querySelector(".fg");
  fg.style.strokeDashoffset = 264 * (1 - f);
  fg.style.stroke = warn ? "var(--bad)" : "var(--c1)";
  el.querySelector("b").textContent = text;
}

const n = (v, unit = "") => (v === null || v === undefined ? "–" : v + unit);
const fmtMB = mb => (mb === null || mb === undefined ? "–" : (mb / 1024).toFixed(1) + " GB");
const fmtRate = k => (k >= 1000 ? (k / 1000).toFixed(1) + " Mbit" : k + " kbit");

function render(s) {
  const g = s.gpu || {}, c = s.cpu || {}, r = s.ram || {}, net = s.net || {};
  $("host").textContent = s.host || "PC";
  setRing("gpu_temp", (g.temp_c || 0) / 100, n(g.temp_c), (g.temp_c || 0) >= 80);
  setRing("gpu_util", (g.util_pct || 0) / 100, n(g.util_pct), false);
  const vf = g.vram_total_mb ? g.vram_used_mb / g.vram_total_mb : 0;
  setRing("vram", vf, g.vram_total_mb ? Math.round(vf * 100) + "%" : "–", vf > 0.95);
  $("gpu_power").textContent = n(g.power_w, " W") + (g.power_limit_w ? " / " + g.power_limit_w : "");
  $("gpu_clock").textContent = n(g.clock_mhz, " MHz");
  $("gpu_vram").textContent = fmtMB(g.vram_used_mb) + " / " + fmtMB(g.vram_total_mb);
  $("cpu").textContent = n(c.util_pct, " %") + " · " + n(c.freq_mhz, " MHz");
  $("cpu_temp").textContent = n(c.temp_c, " °C");
  $("ram").textContent = fmtMB(r.used_mb) + " / " + fmtMB(r.total_mb);
  $("net").textContent = fmtRate(net.up_kbps || 0) + " / " + fmtRate(net.down_kbps || 0);
  $("disks").textContent = (s.disks || []).map(d => d.mount + " " + d.used_pct + "%").join("  ") || "–";
  const u = s.uptime_s || 0;
  $("uptime").textContent = Math.floor(u / 3600) + " h " + Math.floor((u % 3600) / 60) + " min";
  for (const [k, v] of [["gpu", g.util_pct], ["cpu", c.util_pct], ["temp", g.temp_c]]) {
    hist[k].push(v || 0);
    if (hist[k].length > 60) hist[k].shift();
  }
  drawGraph();
}

function drawGraph() {
  const cv = $("graph"), ctx = cv.getContext("2d"), w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#15212b";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) { ctx.beginPath(); ctx.moveTo(0, h * i / 4); ctx.lineTo(w, h * i / 4); ctx.stroke(); }
  const line = (arr, color) => {
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
    arr.forEach((v, i) => {
      const x = w * i / 59, y = h - (Math.min(v, 100) / 100) * (h - 6) - 3;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  };
  line(hist.gpu, "#39ff88"); line(hist.cpu, "#4db8ff"); line(hist.temp, "#ffb347");
}

function onMessage(m) {
  const badge = $("badge");
  badge.textContent = { online: "online", offline: "offline", waking: "startet" }[m.status] || m.status;
  badge.className = "badge " + m.status;
  $("warn").hidden = m.api_ok;
  if (m.status === "online") {
    show("live");
    if (m.snapshot) render(m.snapshot);
  } else if (m.status === "waking") {
    show("waking");
    $("countdown").textContent = "noch bis zu " + (m.waking_left ?? "?") + " s";
  } else {
    show("offline");
    $("wake").disabled = !m.wol_configured;
    if (!m.wol_configured) $("wakemsg").textContent = "pc_mac im Add-on nicht konfiguriert.";
    for (const k in hist) hist[k].length = 0;
  }
}

function connect() {
  if (!token) { show("login"); return; }
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const base = location.pathname.replace(/[^/]*$/, "");
  ws = new WebSocket(proto + location.host + base + "ws?token=" + encodeURIComponent(token));
  ws.onopen = () => { retry = 1000; };
  ws.onmessage = e => onMessage(JSON.parse(e.data));
  ws.onclose = ev => {
    if (ev.code === 4401) { token = ""; store.set("pcc_ui_token", ""); show("login"); return; }
    $("badge").textContent = "Hub getrennt"; $("badge").className = "badge offline";
    setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
  };
}

$("save").onclick = () => { token = $("token").value.trim(); store.set("pcc_ui_token", token); connect(); };
$("wake").onclick = async () => {
  $("wakemsg").textContent = "Sende Magic Packet …";
  try {
    const r = await fetch("api/wake", { method: "POST", headers: { Authorization: "Bearer " + token } });
    $("wakemsg").textContent = r.ok ? "" : "Fehler: " + (await r.json()).detail;
  } catch (e) { $("wakemsg").textContent = "Hub nicht erreichbar"; }
};
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

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
connect();
