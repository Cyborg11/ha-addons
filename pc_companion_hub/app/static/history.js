"use strict";
// Langzeitverlauf: Karte „Verlauf“ im Dashboard (Daten kommen vom Hub, nicht vom Agenten).
(function () {
  const $ = id => document.getElementById(id);
  const META = {
    gpu: { label: "GPU-Last", unit: "%", color: "--gpu", max: 100 },
    temp: { label: "GPU-Temperatur", unit: "°C", color: "--temp" },
    power: { label: "GPU-Leistung", unit: "W", color: "--gpu" },
    vram: { label: "VRAM", unit: "%", color: "--ram", max: 100 },
    cpu: { label: "CPU", unit: "%", color: "--cpu", max: 100 },
    ram: { label: "RAM", unit: "%", color: "--net", max: 100 },
  };
  const RANGES = { 1: "1 Std.", 6: "6 Std.", 24: "24 Std.", 168: "7 Tage" };
  let hours = Number(store.get("pcc_hrange")) || 6, metric = store.get("pcc_hmetric") || "gpu";
  if (!RANGES[hours]) hours = 6;
  if (!META[metric]) metric = "gpu";
  let data = null, loadedAt = 0, loadedPc = "", busy = false;

  function seg(boxId, items, active, onPick) {
    const box = $(boxId);
    box.textContent = "";
    for (const [key, label] of items) {
      const b = document.createElement("button");
      b.className = "segbtn" + (String(key) === String(active) ? " on" : "");
      b.textContent = label;
      b.onclick = () => onPick(key);
      box.append(b);
    }
  }

  function renderControls() {
    seg("h_range", Object.entries(RANGES), hours, k => { hours = Number(k); store.set("pcc_hrange", hours); renderControls(); load(true); });
    seg("h_metric", Object.entries(META).map(([k, m]) => [k, m.label]), metric, k => { metric = k; store.set("pcc_hmetric", k); renderControls(); draw(); });
  }

  const fmtTime = t => {
    const d = new Date(t * 1000);
    return hours > 24 ? d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  };

  async function load(force) {
    const card = $("histcard");
    if (!card || busy) return;
    if (!force && loadedPc === current && Date.now() - loadedAt < 60000) return;
    busy = true;
    try {
      const r = await fetch(pcq("api/history?hours=" + hours), { headers: authHeaders() });
      if (r.ok) { data = await r.json(); loadedAt = Date.now(); loadedPc = current; draw(); }
    } catch (e) { /* nächster Versuch */ }
    busy = false;
  }

  function draw() {
    const cv = $("g_hist");
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const m = META[metric];
    const pts = ((data && data.points) || []).filter(p => p[metric] != null);
    $("h_sum").textContent = "";
    if (pts.length < 2) {
      ctx.fillStyle = css("--dim"); ctx.font = "13px system-ui,sans-serif"; ctx.textAlign = "center";
      ctx.fillText(data ? "Noch zu wenig Daten – der Hub sammelt ab jetzt alle 30 s." : "Lade …", w / 2, h / 2);
      return;
    }
    const vals = pts.map(p => p[metric]);
    const lo = 0, rawMax = Math.max(...vals);
    const top = m.max || Math.max(10, Math.ceil(rawMax * 1.15 / 10) * 10);
    const padL = 34, padB = 18, padT = 6, cw = w - padL - 6, ch = h - padB - padT;
    const t0 = data.points[0].t, t1 = data.points[data.points.length - 1].t, span = Math.max(1, t1 - t0);
    ctx.font = "10px system-ui,sans-serif"; ctx.fillStyle = css("--dim"); ctx.strokeStyle = "rgba(255,255,255,.06)"; ctx.lineWidth = 1;
    ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = Math.round(padT + ch * i / 4) + .5;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - 6, y); ctx.stroke();
      ctx.fillText(Math.round(top - (top - lo) * i / 4), padL - 5, y + 3);
    }
    ctx.textAlign = "left"; ctx.fillText(fmtTime(t0), padL, h - 4);
    ctx.textAlign = "center"; ctx.fillText(fmtTime(t0 + span / 2), padL + cw / 2, h - 4);
    ctx.textAlign = "right"; ctx.fillText(fmtTime(t1), w - 6, h - 4);
    const X = t => padL + cw * (t - t0) / span, Y = v => padT + ch - Math.min(v / top, 1) * ch;
    const gap = (data.bucket_s || 30) * 2.5;
    const col = css(m.color);
    let prev = null, run = [];
    const flush = () => {
      if (run.length < 2) { run = []; return; }
      ctx.beginPath();
      run.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
      ctx.lineTo(run[run.length - 1][0], padT + ch); ctx.lineTo(run[0][0], padT + ch); ctx.closePath();
      const g = ctx.createLinearGradient(0, padT, 0, padT + ch);
      g.addColorStop(0, col + "55"); g.addColorStop(1, col + "00");
      ctx.fillStyle = g; ctx.fill(); ctx.fillStyle = css("--dim");
      run = [];
    };
    for (const p of pts) {
      if (prev && p.t - prev.t > gap) flush();        // Lücke (PC war aus): Linie unterbrechen
      run.push([X(p.t), Y(p[metric])]); prev = p;
    }
    flush();
    const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
    $("h_sum").textContent = m.label + ": Ø " + avg.toFixed(m.unit === "W" ? 0 : 1) + " " + m.unit + " · max " + rawMax.toFixed(m.unit === "W" ? 0 : 1) + " " + m.unit
      + " · min " + Math.min(...vals).toFixed(m.unit === "W" ? 0 : 1) + " " + m.unit;
  }

  renderControls();
  window.addEventListener("pcc:status", ev => { if (ev.detail === "online" && tab === "dash") load(false); });
  window.addEventListener("pcc:pc", () => { data = null; loadedPc = ""; });
  window.addEventListener("pcc:histshow", () => { load(true); setTimeout(draw, 60); });   // Offline-Seite: der Verlauf liegt im Hub und ist auch ohne PC da
  window.addEventListener("resize", () => { if (tab === "dash" && !$("live").hidden) draw(); });
  setInterval(() => { if (tab === "dash" && !$("live").hidden) load(true); }, 60000);
  document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => { if (b.dataset.tab === "dash") setTimeout(() => { load(false); draw(); }, 50); }));
})();
