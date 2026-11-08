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
  for (const id of ["login", "overview", "offline", "waking", "live"]) $(id).hidden = id !== view;
  $("tabs").hidden = view !== "live";
  $("pcbar").hidden = pcList.length < 2 || view === "login";
  document.body.classList.toggle("is-live", view === "live");
}

function showTab(name) {
  tab = ["dash", "tools", "ctrl", "files"].includes(name) ? name : "dash";
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
  renderJob(s);
  if (tab === "dash") drawAll();
}

/* ---------------- Job-Status (KI-Tools) ---------------- */
const JOB_STATE = { queued: "wartet", running: "läuft", done: "fertig", error: "Fehler" };
let previewKey = "", previewUrl = null, previewBusy = false;

function fmtEta(sec) {
  if (sec == null) return "";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return "noch " + (m ? m + ":" + String(s).padStart(2, "0") + " min" : s + " s");
}

async function loadPreview(job) {
  const key = job.job_id + ":" + job.preview_ver;
  if (previewBusy || key === previewKey) return;
  previewBusy = true;
  try {
    const r = await fetch(pcq("api/job/" + encodeURIComponent(job.job_id) + "/preview"), { headers: authHeaders() });
    if (r.ok) {
      const url = URL.createObjectURL(await r.blob());
      $("jpic").src = url;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = url; previewKey = key;
    }
  } catch (e) { /* nächster Versuch beim nächsten Update */ }
  previewBusy = false;
}

function renderJob(s) {
  const j = s.job, card = $("job");
  card.hidden = !j;
  if (!j) { previewKey = ""; return; }
  card.className = "panel job st-" + j.state;
  $("jtool").textContent = j.tool;
  $("jstate").textContent = JOB_STATE[j.state] || j.state;
  $("jtitle").textContent = (j.state === "error" && j.message) ? j.message : (j.title || "");
  $("jpct").textContent = Math.round(j.progress * 100) + " %";
  $("jbar").style.width = Math.round(j.progress * 100) + "%";
  $("jeta").textContent = j.state === "running" ? fmtEta(j.eta_s) : "";
  const more = (s.jobs || []).length - 1;
  $("jmore").textContent = more > 0 ? "+" + more + " weitere" : "";
  $("jimg").hidden = !j.has_preview;
  if (j.has_preview) loadPreview(j);
}

/* ---------------- KI-Tools (Kacheln) ---------------- */
let toolsKey = "";
function renderTools(list) {
  const key = JSON.stringify(list);
  if (key === toolsKey) return;
  toolsKey = key;
  const box = $("tiles");
  box.innerHTML = "";
  $("notools").hidden = list.length > 0;
  for (const t of list) {
    let u;
    try { u = new URL(t.url); } catch (e) { continue; }
    if (u.protocol !== "http:" && u.protocol !== "https:") continue;
    const a = document.createElement("a");
    a.className = "tile"; a.href = u.href; a.target = "_blank"; a.rel = "noopener";
    const d = document.createElement("div");
    const b = document.createElement("b"); b.textContent = t.name;
    const sm = document.createElement("small"); sm.textContent = u.host;
    d.append(b, sm);
    a.append(d);
    a.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24"><path d="M7 17L17 7M9 7h8v8"/></svg>');
    box.appendChild(a);
  }
}

/* ---------------- Mehrere PCs ---------------- */
const ALL = "__all";
let pcList = [], states = {}, current = store.get("pcc_pc") || "";

// hängt ?pc=<id> an Hub-Aufrufe (ohne Angabe nimmt der Hub den ersten PC)
function pcq(url, id) {
  const pc = id || current;
  if (!pc || pc === ALL) return url;
  return url + (url.includes("?") ? "&" : "?") + "pc=" + encodeURIComponent(pc);
}
const pcName = id => {
  const p = pcList.find(x => x.id === id), s = states[id];
  return (p && p.name) || (s && (s.name || s.host)) || "PC";
};
const STATUS_TEXT = { online: "online", offline: "offline", waking: "startet" };

function setPcs(m) {
  pcList = m.pcs || [];
  if (pcList.length < 2 && current === ALL) current = "";
  if (current !== ALL && !pcList.some(p => p.id === current)) current = m.default || (pcList[0] && pcList[0].id) || "";
  renderBar();
}

function renderBar() {
  const bar = $("pcbar");
  bar.hidden = pcList.length < 2 || !$("login").hidden;
  if (bar.hidden) return;
  bar.textContent = "";
  for (const p of [{ id: ALL, name: "Alle" }, ...pcList]) {
    const b = document.createElement("button");
    b.className = "chip" + (p.id === current ? " on" : "");
    if (p.id !== ALL) {
      const d = document.createElement("i");
      d.className = "dot st-" + ((states[p.id] || {}).status || "offline");
      b.append(d);
    }
    b.append(p.name || pcName(p.id));
    b.onclick = () => selectPc(p.id);
    bar.append(b);
  }
}

function selectPc(id) {
  if (id === current) return;
  current = id; store.set("pcc_pc", id);
  for (const k in hist) hist[k].length = 0;
  previewKey = ""; toolsKey = "";
  renderBar();
  window.dispatchEvent(new CustomEvent("pcc:pc", { detail: id }));
  if (id === ALL) { showOverview(); return; }
  if (states[id]) applyState(states[id]);
}

/* Übersicht: eine Karte je PC, wird an Ort und Stelle aktualisiert (damit Klicks nicht verloren gehen) */
const ovCards = {};
function showOverview() {
  show("overview");
  $("host").textContent = "Alle PCs"; $("sub").textContent = "";
  $("badge").textContent = "Übersicht"; $("badge").className = "badge";
  $("warn").hidden = true;
  renderOverview();
}

function ovCard(p) {
  const root = document.createElement("div");
  root.className = "panel pad ov";
  root.innerHTML = '<div class="ovhead"><i class="dot"></i><b class="ovname"></b><span class="ovstate"></span></div>'
    + '<div class="ovstats"></div><div class="ovjob" hidden></div>'
    + '<div class="row"><button class="ovopen primary">Öffnen</button><button class="ovwake" hidden>Aufwecken</button></div><div class="ovmsg"></div>';
  const c = { root, dot: root.querySelector(".dot"), name: root.querySelector(".ovname"), state: root.querySelector(".ovstate"),
    stats: root.querySelector(".ovstats"), job: root.querySelector(".ovjob"), wake: root.querySelector(".ovwake"), msg: root.querySelector(".ovmsg") };
  root.querySelector(".ovopen").onclick = () => selectPc(p.id);
  c.wake.onclick = async () => {
    c.msg.textContent = "Sende Magic Packet …";
    try {
      const r = await fetch(pcq("api/wake", p.id), { method: "POST", headers: authHeaders() });
      c.msg.textContent = r.ok ? "" : "Fehler: " + ((await r.json().catch(() => ({}))).detail || r.status);
    } catch (e) { c.msg.textContent = "Hub nicht erreichbar"; }
  };
  return c;
}

function renderOverview() {
  const grid = $("ovgrid");
  for (const p of pcList) {
    if (!ovCards[p.id]) { ovCards[p.id] = ovCard(p); grid.append(ovCards[p.id].root); }
    const c = ovCards[p.id], m = states[p.id];
    c.name.textContent = p.name || pcName(p.id);
    const st = m ? m.status : "offline";
    c.dot.className = "dot st-" + st;
    c.state.textContent = m ? (STATUS_TEXT[st] || st) + (st === "waking" && m.waking_left != null ? " (" + m.waking_left + " s)" : "") : "…";
    c.wake.hidden = !(m && st === "offline" && m.wol_configured);
    const s = m && m.snapshot;
    c.stats.textContent = "";
    if (st === "online" && s) {
      const g = s.gpu || {}, cpu = s.cpu || {}, r = s.ram || {};
      const vf = g.vram_total_mb ? Math.round(100 * g.vram_used_mb / g.vram_total_mb) : null;
      const rf = r.total_mb ? Math.round(100 * r.used_mb / r.total_mb) : null;
      for (const [label, val, lv] of [["GPU", n(g.util_pct, " %"), level(g.util_pct || 0, 90, 101)], ["Temp", n(g.temp_c, " °C"), level(g.temp_c || 0, 70, 82)],
        ["VRAM", n(vf, " %"), level(vf || 0, 85, 95)], ["CPU", n(cpu.util_pct != null ? Math.round(cpu.util_pct) : null, " %"), "ok"], ["RAM", n(rf, " %"), level(rf || 0, 85, 95)]]) {
        const d = document.createElement("div");
        d.className = "ovstat lv-" + lv;
        const sm = document.createElement("small"), b = document.createElement("b");
        sm.textContent = label; b.textContent = val;
        d.append(sm, b);
        c.stats.append(d);
      }
    }
    const j = s && s.job;
    c.job.hidden = !(st === "online" && j);
    if (!c.job.hidden) c.job.textContent = j.tool + ": " + (j.title || JOB_STATE[j.state] || j.state) + " · " + Math.round(j.progress * 100) + " % · " + (JOB_STATE[j.state] || j.state);
  }
}

/* ---------------- Verbindung ---------------- */
function onMessage(m) {
  if (m.pcs) { setPcs(m); return; }
  states[m.pc] = m;
  renderBar();
  if (current === ALL) { if ($("overview").hidden) showOverview(); else renderOverview(); return; }
  if (m.pc === current) applyState(m);
}

function applyState(m) {
  window.dispatchEvent(new CustomEvent("pcc:status", { detail: m.status }));
  const badge = $("badge");
  badge.textContent = STATUS_TEXT[m.status] || m.status;
  badge.className = "badge " + m.status;
  $("warn").hidden = m.api_ok;
  renderTools(m.tools || []);
  if (m.status === "online") {
    if ($("live").hidden) { show("live"); showTab(tab); }
    if (m.snapshot) { render(m.snapshot); $("host").textContent = m.name || m.snapshot.host || "PC"; }
  } else if (m.status === "waking") {
    show("waking");
    $("host").textContent = m.name || m.host || "PC-Companion";
    $("sub").textContent = "";
    $("countdown").textContent = "noch bis zu " + (m.waking_left ?? "?") + " s";
  } else {
    show("offline");
    $("host").textContent = m.name || m.host || "PC-Companion";
    $("sub").textContent = "";
    $("wake").disabled = !m.wol_configured;
    $("wakemsg").textContent = m.wol_configured ? "" : "MAC-Adresse im Add-on nicht konfiguriert.";
    for (const k in hist) hist[k].length = 0;
  }
}

let trusted = false, authInfo = null, tokenMode = false;
const authHeaders = () => (token ? { Authorization: "Bearer " + token } : {});

async function fetchAuthInfo() {
  if (authInfo) return authInfo;
  try { authInfo = await (await fetch("api/auth/info")).json(); } catch (e) { authInfo = null; }
  return authInfo;
}

// Start: Kopplungslink (#pair=…) einlösen, sonst gespeichertes Gerätetoken nutzen, sonst Ingress/Anmeldung.
async function start() {
  const m = /^#pair=(.+)$/.exec(location.hash);
  if (m) {
    history.replaceState(null, "", location.pathname + location.search);
    await finishLogin("api/pair/redeem", { code: decodeURIComponent(m[1]) });
    return;
  }
  if (token) { connect(); return; }
  const info = await fetchAuthInfo();
  if (!info) { // Hub nicht erreichbar
    $("badge").textContent = "Hub getrennt"; $("badge").className = "badge offline";
    setTimeout(start, retry); retry = Math.min(retry * 2, 10000);
    return;
  }
  if (info.trusted) { trusted = true; connect(); return; }
  askToken("");
}

async function finishLogin(url, body) {
  $("loginmsg").textContent = "…";
  try {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { $("token").value = ""; askToken(d.detail || ("Fehler " + r.status)); return; }
    token = d.token; trusted = false;
    store.set("pcc_ui_token", token); store.set("pcc_device_id", (d.device && d.device.id) || "");
    $("token").value = ""; $("loginmsg").textContent = "";
    connect();
  } catch (e) { askToken("Hub nicht erreichbar"); }
}

function connect() {
  if (!token && !trusted) { if ($("login").hidden) askToken(""); return; }
  const proto = location.protocol === "https:" ? "wss://" : "ws://";
  const base = location.pathname.replace(/[^/]*$/, "");
  ws = new WebSocket(proto + location.host + base + "ws?token=" + encodeURIComponent(token));
  let opened = false;
  ws.onopen = () => { opened = true; retry = 1000; };
  ws.onmessage = e => onMessage(JSON.parse(e.data));
  ws.onclose = async () => {
    // Der Hub lehnt unbekannte Tokens schon beim Handshake ab (HTTP 403) – der Browser meldet dann
    // nur Code 1006. Deshalb per REST prüfen, ob die Anmeldung abgelehnt wurde.
    if (!opened) {
      try {
        const r = await fetch("api/status", { headers: authHeaders() });
        if (r.status === 401) {
          const had = !!token;
          trusted = false;
          askToken(had ? "Anmeldung abgelaufen oder Gerät entfernt – bitte neu anmelden." : "");
          return;
        }
      } catch (e) { /* Hub nicht erreichbar */ }
    }
    $("badge").textContent = "Hub getrennt"; $("badge").className = "badge offline";
    setTimeout(connect, retry); retry = Math.min(retry * 2, 10000);
  };
}

async function askToken(msg) {
  token = ""; store.set("pcc_ui_token", ""); store.set("pcc_device_id", "");
  if (ws) { ws.onclose = null; try { ws.close(); } catch (e) { /* schon zu */ } ws = null; }
  const info = await fetchAuthInfo();
  tokenMode = !(info && info.pin);
  renderLoginMode(info);
  $("loginmsg").textContent = msg || "";
  $("badge").textContent = "Anmeldung nötig"; $("badge").className = "badge offline";
  show("login");
}

function renderLoginMode(info) {
  const pin = !tokenMode;
  $("loginhint").textContent = pin ? "PIN eingeben" : "Token eingeben";
  $("token").placeholder = pin ? "PIN" : "Token";
  $("token").inputMode = pin && info && info.pin_numeric ? "numeric" : "text";
  $("switchmode").hidden = !(info && info.pin);
  $("switchmode").textContent = pin ? "Stattdessen Token eingeben" : "Stattdessen PIN eingeben";
}
$("switchmode").onclick = () => { tokenMode = !tokenMode; renderLoginMode(authInfo); $("token").focus(); };
$("loginform").onsubmit = e => {
  e.preventDefault();
  const secret = $("token").value.trim();
  if (secret) finishLogin("api/login", { secret });
};
$("wake").onclick = async () => {
  $("wakemsg").textContent = "Sende Magic Packet …";
  try {
    const r = await fetch(pcq("api/wake"), { method: "POST", headers: authHeaders() });
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
start();
