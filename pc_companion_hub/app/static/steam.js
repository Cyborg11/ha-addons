"use strict";
// Tab „Spiele“ (Phase 9): Steam-Bibliothek des PCs, „Läuft gerade“, Starten und Beenden.
(function () {
  const $ = id => document.getElementById(id);
  const REFRESH_MS = 30000;
  let games = [], loadedPc = "", loadedAt = 0, loading = false, openId = 0, running = null, down = null;
  let sort = store.get("pcc_steam_sort") || "recent", query = "";
  const covers = new Map();                      // "pc|appid|art_ver|w" -> Blob-URL
  const heroes = new Map();
  const view = document.querySelector('[data-view="steam"]');

  async function call(method, path, body) {
    const r = await fetch(pcq(path), {
      method, headers: { ...authHeaders(), ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(d.detail || ("Fehler " + r.status)); e.status = r.status; throw e; }
    return d;
  }

  // Bilder höchstens 4 gleichzeitig laden
  let active = 0;
  const queue = [];
  function pump() {
    while (active < 4 && queue.length) { const job = queue.shift(); active++; job().finally(() => { active--; pump(); }); }
  }
  function loadArt(img, appid, kind, w, ver, cache, then) {
    const key = current + "|" + appid + "|" + ver + "|" + w + "|" + kind;
    if (cache.has(key)) { img.src = cache.get(key); if (then) then(true); return; }
    queue.push(async () => {
      try {
        const r = await fetch(pcq("api/steam/art/" + appid + "/" + kind + "?w=" + w), { headers: authHeaders() });
        if (!r.ok) throw new Error();
        const url = URL.createObjectURL(await r.blob());
        cache.set(key, url); img.src = url; if (then) then(true);
      } catch (e) { if (then) then(false); }
    });
    pump();
  }
  const lazy = "IntersectionObserver" in window ? new IntersectionObserver(entries => {
    for (const en of entries) if (en.isIntersecting) { lazy.unobserve(en.target); en.target._load(); }
  }, { rootMargin: "300px" }) : null;

  const fmtH = min => min == null ? "–" : min < 60 ? min + " Min." : (min / 60).toFixed(min < 600 ? 1 : 0).replace(".", ",") + " Std.";
  const fmtGb = g => g == null ? "–" : g >= 100 ? Math.round(g) + " GB" : g.toFixed(1).replace(".", ",") + " GB";
  const STATE = { installed: "", update_required: "Update", updating: "Lädt", downloading: "Lädt", paused: "Pausiert", other: "" };
  const badge = g => {
    if (running && running.appid === g.appid) return "Läuft";
    if (g.progress != null && g.state !== "paused") return "Lädt " + Math.round(g.progress * 100) + " %";
    return STATE[g.state] || "";
  };

  /* ---- Raster ---- */
  const cmp = {
    recent: (a, b) => (b.last_played || 0) - (a.last_played || 0) || a.name.localeCompare(b.name, "de"),
    name: (a, b) => a.name.localeCompare(b.name, "de"),
    size: (a, b) => (b.size_gb || 0) - (a.size_gb || 0),
  };

  function paintGrid() {
    const grid = $("st_grid"), q = query.trim().toLowerCase();
    const list = games.filter(g => !q || g.name.toLowerCase().includes(q)).sort(cmp[sort] || cmp.recent);
    grid.textContent = "";
    for (const g of list) {
      const b = document.createElement("button");
      b.className = "sttile" + (running && running.appid === g.appid ? " live" : "");
      b.title = g.name;
      const frame = document.createElement("div");
      frame.className = "stcover";
      const img = document.createElement("img");
      img.alt = ""; img.decoding = "async";
      const ph = document.createElement("span");
      ph.className = "stph"; ph.textContent = g.name;
      frame.append(ph, img);
      const t = badge(g);
      if (t) { const s = document.createElement("span"); s.className = "stbadge" + (t === "Läuft" ? " run" : ""); s.textContent = t; frame.append(s); }
      const cap = document.createElement("span");
      cap.className = "gcap"; cap.textContent = g.name;
      b.append(frame, cap);
      b.onclick = () => openSheet(g.appid);
      img._load = () => loadArt(img, g.appid, "cover", 300, g.art_ver, covers, ok => { if (ok) ph.hidden = true; });
      grid.append(b);
      if (lazy) lazy.observe(img); else img._load();
    }
    $("st_count").textContent = q ? list.length + " von " + games.length : games.length + " installiert";
    $("st_msg").textContent = list.length ? "" : (games.length ? "Kein Spiel gefunden." : "Keine installierten Spiele gefunden.");
  }

  async function load(force) {
    if (loading || !features.includes("steam")) return;
    loading = true;
    try {
      const d = await call("GET", "api/steam/games?sort=recent");
      games = d.games || []; loadedPc = current; loadedAt = Date.now();
      if (!view.hidden) paintGrid();
      if (!$("st_sheet").hidden) paintSheet();
    } catch (e) { $("st_msg").textContent = e.message; }
    loading = false;
  }

  /* ---- Läuft gerade ---- */
  function runtime(since) {
    if (!since) return "";
    const m = Math.max(0, Math.round((Date.now() / 1000 - since) / 60));
    return m < 1 ? "gerade gestartet" : "seit " + (m < 90 ? m + " Min." : Math.floor(m / 60) + " Std. " + (m % 60) + " Min.");
  }
  let heroApp = 0;
  function paintNow() {
    const box = $("st_now");
    box.hidden = !running;
    $("st_dl").hidden = !down;
    if (down) $("st_dl").textContent = "Lädt: " + down.name + (down.progress != null ? " – " + Math.round(down.progress * 100) + " %" : "");
    if (!running) { heroApp = 0; return; }
    $("st_now_name").textContent = running.name;
    $("st_now_time").textContent = runtime(running.since);
    if (heroApp !== running.appid) {
      heroApp = running.appid;
      const g = games.find(x => x.appid === running.appid), probe = new Image();
      $("st_now_bg").style.backgroundImage = "";
      loadArt(probe, running.appid, "hero", 640, g ? g.art_ver : 0, heroes, ok => { if (ok && heroApp === running.appid) $("st_now_bg").style.backgroundImage = "url(" + probe.src + ")"; });
    }
  }

  window.addEventListener("pcc:snap", e => {
    const st = e.detail && e.detail.steam;
    const prev = running && running.appid;
    running = st ? st.running : null;
    down = st ? st.downloading : null;
    if (!view.hidden || !$("st_now").hidden || running) paintNow();
    if (!view.hidden && (running ? running.appid : 0) !== (prev || 0)) { paintGrid(); load(true); }
    if (!$("st_sheet").hidden) paintSheet();
  });

  $("st_now_stop").onclick = () => stopGame(running && running.appid, running && running.name);

  /* ---- Detail ---- */
  function openSheet(appid) { openId = appid; $("st_sheet").hidden = false; $("st_sheet_msg").textContent = ""; paintSheet(); }
  function closeSheet() { openId = 0; $("st_sheet").hidden = true; }
  $("st_sheet_close").onclick = closeSheet;
  $("st_sheet").addEventListener("click", e => { if (e.target === $("st_sheet")) closeSheet(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("st_sheet").hidden) closeSheet(); });

  let sheetArt = 0;
  function paintSheet() {
    const g = games.find(x => x.appid === openId);
    if (!g) { closeSheet(); return; }
    const isRun = running && running.appid === g.appid;
    $("st_sheet_name").textContent = g.name;
    const rows = [
      ["Zuletzt gespielt", g.last_played ? ago(Date.now() / 1000 - g.last_played) : "noch nie"],
      ["Spielzeit", fmtH(g.playtime_min)], ["Größe", fmtGb(g.size_gb)],
      ["Status", isRun ? "Läuft " + runtime(running.since) : ({ installed: "Installiert", update_required: "Update verfügbar", updating: "Update läuft", downloading: "Wird geladen", paused: "Download pausiert", other: "–" })[g.state]],
    ];
    const box = $("st_sheet_meta");
    box.textContent = "";
    for (const [k, v] of rows) { const d = document.createElement("div"), a = document.createElement("span"), b = document.createElement("b"); a.textContent = k; b.textContent = v; d.append(a, b); box.append(d); }
    $("st_launch").hidden = isRun; $("st_launch").disabled = !g.launchable;
    $("st_stop").hidden = !isRun;
    if (sheetArt !== g.appid) {
      sheetArt = g.appid;
      const img = $("st_sheet_img");
      img.removeAttribute("src");
      loadArt(img, g.appid, "cover", 600, g.art_ver, covers);
    }
  }

  async function launch(appid, name, force) {
    const msg = $("st_sheet_msg");
    msg.textContent = "Starte …";
    try {
      await call("POST", "api/steam/games/" + appid + "/launch", force ? { force: true } : null);
      msg.textContent = "Start ausgelöst. Wenn Steam noch nicht läuft, dauert es bis zu eine Minute.";
    } catch (e) {
      if (e.status === 409 && !force) {
        if (confirm(e.message + "\n\n„" + name + "“ trotzdem starten?")) return launch(appid, name, true);
        msg.textContent = "";
      } else msg.textContent = e.message;
    }
  }
  async function stopGame(appid, name) {
    if (!appid || !confirm("„" + name + "“ beenden? Nicht gespeicherter Fortschritt geht verloren.")) return;
    const msg = $("st_sheet_msg");
    const out = $("st_sheet").hidden ? $("st_msg") : msg;
    try { const d = await call("POST", "api/steam/games/" + appid + "/stop"); out.textContent = "Beendet (" + d.processes + " Prozesse)."; }
    catch (e) { out.textContent = e.message; }
  }
  $("st_launch").onclick = () => { const g = games.find(x => x.appid === openId); if (g) launch(g.appid, g.name, false); };
  $("st_stop").onclick = () => { const g = games.find(x => x.appid === openId); if (g) stopGame(g.appid, g.name); };

  /* ---- Steuerleiste ---- */
  $("st_sort").value = cmp[sort] ? sort : "recent";
  $("st_sort").onchange = () => { sort = $("st_sort").value; store.set("pcc_steam_sort", sort); paintGrid(); };
  let qt;
  $("st_q").oninput = () => { clearTimeout(qt); qt = setTimeout(() => { query = $("st_q").value; paintGrid(); }, 150); };
  $("st_reload").onclick = async () => { await load(true); paintGrid(); };

  window.addEventListener("pcc:pc", () => {
    games = []; loadedPc = ""; running = null; down = null; heroApp = 0; sheetArt = 0; closeSheet();
    $("st_grid").textContent = "";
    for (const m of [covers, heroes]) { m.forEach(u => URL.revokeObjectURL(u)); m.clear(); }
  });

  new MutationObserver(async () => {
    if (view.hidden) return;
    if (loadedPc !== current || Date.now() - loadedAt > REFRESH_MS) { await load(true); }
    paintGrid(); paintNow();
  }).observe(view, { attributes: true, attributeFilter: ["hidden"] });
})();
