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
        const r = await fetch(pcq("api/steam/art/" + appid + "/" + kind + "?w=" + w + "&v=" + (ver || 0)), { headers: authHeaders() });   // v: neue Bilder bekommen eine neue Adresse, sonst hielte der Browser das alte 24 h
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
    return STATE[g.state] || (g.non_steam ? "Eigenes" : "");
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
      saveRecent();
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
      ...(g.non_steam ? [["Quelle", "Eigene Verknüpfung (Nicht-Steam)"]] : [["Spielzeit", fmtH(g.playtime_min)], ["Größe", fmtGb(g.size_gb)]]),
      ["Status", isRun ? "Läuft " + runtime(running.since) : ({ installed: "Installiert", update_required: "Update verfügbar", updating: "Update läuft", downloading: "Wird geladen", paused: "Download pausiert", other: "–" })[g.state]],
    ];
    const box = $("st_sheet_meta");
    box.textContent = "";
    for (const [k, v] of rows) { const d = document.createElement("div"), a = document.createElement("span"), b = document.createElement("b"); a.textContent = k; b.textContent = v; d.append(a, b); box.append(d); }
    $("st_launch").hidden = isRun; $("st_launch").disabled = !g.launchable;
    $("st_update").hidden = !(features.includes("steam_update") && !g.non_steam && !isRun && g.state === "update_required");
    $("st_stop").hidden = !isRun;
    const sk = g.appid + "|" + g.art_ver;                            // auch ein getauschtes Cover im Detailblatt neu laden
    if (sheetArt !== sk) {
      sheetArt = sk;
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
  $("st_update").onclick = async () => {
    const g = games.find(x => x.appid === openId);
    if (!g) return;
    const msg = $("st_sheet_msg");
    msg.textContent = "Starte das Update …";
    try {
      await call("POST", "api/steam/games/" + g.appid + "/update");
      msg.textContent = "Steam prüft die Dateien und lädt das Update. Den Fortschritt siehst du unter „Downloads & Speicher“.";
      setTimeout(async () => { await load(true); paintGrid(); if (!$("st_sheet").hidden) paintSheet(); if ($("st_dlbox").open) loadDownloads(); }, 4000);
    } catch (e) { msg.textContent = e.message; }
  };
  $("st_launch").onclick = () => { const g = games.find(x => x.appid === openId); if (g) launch(g.appid, g.name, false); };
  $("st_stop").onclick = () => { const g = games.find(x => x.appid === openId); if (g) stopGame(g.appid, g.name); };

  /* ---- Downloads & Speicher ---- */
  const dlbox = $("st_dlbox");
  let dlTimer = 0;
  const fmtBytes = b => b == null ? "" : b >= 1e9 ? (b / 1e9).toFixed(1).replace(".", ",") + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB";
  const fmtTb = g => g == null ? "–" : g >= 1000 ? (g / 1000).toFixed(2).replace(".", ",") + " TB" : Math.round(g) + " GB";
  function bar(frac, lv) {
    const b = document.createElement("div"), i = document.createElement("i");
    b.className = "bar"; i.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%";
    if (lv) i.className = lv;
    b.append(i); return b;
  }
  function row(left, right) {
    const d = document.createElement("div"), a = document.createElement("span"), b = document.createElement("b");
    d.className = "mh"; a.textContent = left; b.textContent = right; d.append(a, b); return d;
  }
  async function loadDownloads() {
    try {
      const [dl, st] = await Promise.all([call("GET", "api/steam/downloads"), call("GET", "api/steam/status")]);
      const list = $("st_dl_list"), libs = $("st_libs");
      list.textContent = ""; libs.textContent = "";
      const names = { updating: "Update läuft", downloading: "Wird geladen", paused: "Pausiert" };
      for (const it of dl.items) {
        const box = document.createElement("div");
        box.className = "dlitem";
        const pct = it.progress == null ? "" : Math.round(it.progress * 100) + " %";
        box.append(row(it.name, pct || names[it.state]));
        if (it.progress != null) box.append(bar(it.progress, it.state === "paused" ? "paused" : ""));
        const sub = document.createElement("small");
        sub.className = "muted";
        sub.textContent = names[it.state] + (it.bytes_total ? " · " + fmtBytes(it.bytes_done) + " von " + fmtBytes(it.bytes_total) : "");
        box.append(sub); list.append(box);
      }
      if (!dl.items.length) { const p = document.createElement("div"); p.className = "muted"; p.textContent = "Es lädt gerade nichts."; list.append(p); }
      if (dl.update_required) { const p = document.createElement("div"); p.className = "muted dlwait"; p.textContent = dl.update_required + (dl.update_required === 1 ? " Spiel wartet" : " Spiele warten") + " auf ein Update (Steam startet es, sobald es dran ist)."; list.append(p); }
      for (const l of st.libraries || []) {
        const box = document.createElement("div");
        box.className = "dlitem";
        const used = l.total_gb ? 1 - (l.free_gb || 0) / l.total_gb : 0;
        box.append(row(l.name, l.free_gb == null ? "–" : fmtTb(l.free_gb) + " frei von " + fmtTb(l.total_gb)));
        box.append(bar(used, used > 0.95 ? "crit" : used > 0.85 ? "warn" : ""));
        const sub = document.createElement("small");
        sub.className = "muted"; sub.textContent = "Steam-Spiele hier: " + fmtTb(l.games_gb);
        box.append(sub); libs.append(box);
      }
      $("st_dl_sum").textContent = dl.items.length ? dl.items.length + " aktiv" : "";
    } catch (e) { $("st_dl_list").textContent = e.message; }
  }
  function dlWatch() {
    clearInterval(dlTimer); dlTimer = 0;
    if (dlbox.open && !view.hidden) { loadDownloads(); dlTimer = setInterval(() => { if (!document.hidden) loadDownloads(); }, 10000); }
  }
  dlbox.addEventListener("toggle", dlWatch);
  $("st_dl_open").onclick = async () => {
    try { await call("POST", "api/steam/open/downloads"); $("st_dl_list").prepend(Object.assign(document.createElement("div"), { className: "muted", textContent: "Die Downloads-Seite ist am PC geöffnet." })); }
    catch (e) { $("st_dl_list").prepend(Object.assign(document.createElement("div"), { className: "muted", textContent: e.message })); }
  };

  /* ---- Bilder ändern (SteamGridDB) ---- */
  const ART_KINDS = [["cover", "Cover", "2/3"], ["header", "Header", "920/430"], ["hero", "Hero", "96/31"], ["logo", "Logo", "16/9"]];
  let artApp = 0, artKind = "cover", artPage = 0, artSel = 0, artSeq = 0;
  const artThumbs = new Map();
  let artNsfw = store.get("pcc_steam_nsfw") === "1";                 // wird pro Gerät gemerkt, Standard: aus
  const artGame = () => games.find(g => g.appid === artApp);

  function openArt(appid) {
    artApp = appid; artKind = "cover";
    $("st_art").hidden = false; $("st_art_note").hidden = true;
    $("st_art_nsfw").checked = artNsfw;
    $("st_art_title").textContent = "Bilder ändern – " + (artGame() || {}).name;
    paintArtTabs(); loadSuggestions(true);
  }
  function closeArt() { artSeq++; artApp = 0; $("st_art").hidden = true; }
  function paintArtTabs() {
    const box = $("st_art_tabs");
    box.textContent = "";
    for (const [k, label] of ART_KINDS) {
      const b = document.createElement("button");
      b.className = "segbtn" + (k === artKind ? " on" : ""); b.textContent = label;
      b.onclick = () => { artKind = k; paintArtTabs(); loadSuggestions(true); };
      box.append(b);
    }
    const g = artGame();
    $("st_art_reset").hidden = !(g && g.has_custom && g.has_custom[artKind]);
  }
  function artMsg(t) { $("st_art_msg").textContent = t || ""; }
  async function loadSuggestions(reset) {
    const my = ++artSeq, grid = $("st_art_grid");
    if (reset) { artPage = 0; artSel = 0; grid.textContent = ""; $("st_art_preview").hidden = true; $("st_art_more").hidden = true; }
    if ((artGame() || {}).non_steam) {
      artMsg("Für Nicht-Steam-Spiele gibt es keine Vorschläge von SteamGridDB. Eigene Bilder lassen sich im grid-Ordner von Steam ablegen.");
      return;
    }
    if (!features.includes("steam_griddb")) {
      artMsg("Für Vorschläge einen SteamGridDB-Schlüssel eintragen: steam.griddb_key in der config.yaml des Agenten (Schlüssel unter steamgriddb.com → Profil → Preferences → API).");
      return;
    }
    artMsg("Lade Vorschläge …");
    try {
      const d = await call("GET", "api/steam/griddb/" + artApp + "/" + artKind + "?page=" + artPage + (artNsfw ? "&nsfw=true" : ""));
      if (my !== artSeq) return;
      const ratio = (ART_KINDS.find(x => x[0] === artKind) || [])[2] || "2/3";
      grid.classList.toggle("wide", artKind === "header" || artKind === "hero" || artKind === "logo");
      for (const it of d.items || []) {
        const b = document.createElement("button");
        b.className = "sttile arttile"; b.dataset.id = it.id;
        const frame = document.createElement("div"), img = document.createElement("img"), cap = document.createElement("span");
        frame.className = "stcover"; frame.style.aspectRatio = ratio; img.alt = "";
        if (it.nsfw) { const nb = document.createElement("span"); nb.className = "stbadge nsfw"; nb.textContent = "NSFW"; frame.append(nb); }
        cap.className = "gcap"; cap.textContent = [it.width && it.height ? it.width + "×" + it.height : "", it.style || ""].filter(Boolean).join(" · ");
        frame.append(img); b.append(frame, cap);
        b.onclick = () => selectArt(it, b);
        grid.append(b);
        loadBlob(img, "api/steam/griddb/thumb/" + it.id);
      }
      artPage = (d.page || 0) + 1;
      $("st_art_more").hidden = !d.has_more;
      artMsg(grid.children.length ? "" : "Keine Vorschläge gefunden.");
    } catch (e) { if (my === artSeq) artMsg(e.message); }
  }
  function loadBlob(img, path) {
    const key = current + "|" + path;
    if (artThumbs.has(key)) { img.src = artThumbs.get(key); return; }
    queue.push(async () => {
      try {
        const r = await fetch(pcq(path), { headers: authHeaders() });
        if (!r.ok) throw new Error();
        const url = URL.createObjectURL(await r.blob());
        artThumbs.set(key, url); img.src = url;
      } catch (e) { /* Platzhalter bleibt */ }
    });
    pump();
  }
  function selectArt(it, btn) {
    artSel = it.id;
    for (const b of $("st_art_grid").children) b.classList.toggle("sel", b === btn);
    const prev = $("st_art_preview");
    prev.hidden = false;
    $("st_art_img").src = btn.querySelector("img").src || "";
    prev.scrollIntoView({ block: "nearest" });
  }
  async function afterArtChange(text) {
    await load(true); paintGrid(); paintArtTabs();
    artMsg(text); $("st_art_note").hidden = false;
  }
  $("st_art_apply").onclick = async () => {
    if (!artSel) return;
    artMsg("Lade das Bild auf den PC …");
    try { await call("PUT", "api/steam/art/" + artApp + "/" + artKind, { griddb_id: artSel }); $("st_art_preview").hidden = true; artSel = 0; await afterArtChange("Gespeichert."); }
    catch (e) { artMsg(e.message); }
  };
  $("st_art_cancel").onclick = () => { artSel = 0; $("st_art_preview").hidden = true; for (const b of $("st_art_grid").children) b.classList.remove("sel"); };
  $("st_art_reset").onclick = async () => {
    if (!confirm("Das eigene Bild entfernen und wieder das Steam-Standardbild verwenden?")) return;
    try { await call("DELETE", "api/steam/art/" + artApp + "/" + artKind); await afterArtChange("Zurückgesetzt."); }
    catch (e) { artMsg(e.message); }
  };
  $("st_art_more").onclick = () => loadSuggestions(false);
  $("st_art_nsfw").onchange = () => { artNsfw = $("st_art_nsfw").checked; store.set("pcc_steam_nsfw", artNsfw ? "1" : "0"); loadSuggestions(true); };
  $("st_art_close").onclick = closeArt;
  $("st_art").addEventListener("click", e => { if (e.target === $("st_art")) closeArt(); });
  $("st_art_exit").onclick = async () => {
    if (!confirm("Steam jetzt beenden? Laufende Spiele und Downloads werden dabei unterbrochen.")) return;
    try { await call("POST", "api/steam/open/exit"); artMsg("Steam wird beendet. Danach am PC wieder starten, dann sind die neuen Bilder sichtbar."); }
    catch (e) { artMsg(e.message); }
  };
  $("st_art_open").onclick = () => { const id = openId; closeSheet(); openArt(id); };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("st_art").hidden) closeArt(); });
  window.addEventListener("pcc:pc", () => { closeArt(); artThumbs.forEach(u => URL.revokeObjectURL(u)); artThumbs.clear(); });

  /* ---- Aufwecken und starten (Offline-Seite, Warte-Seite, Hinweis) ---- */
  const RECENT_KEY = () => "pcc_steam_recent|" + current;
  function saveRecent() {
    const list = games.filter(g => g.launchable).sort(cmp.recent).slice(0, 8).map(g => ({ appid: g.appid, name: g.name, art_ver: g.art_ver }));
    store.set(RECENT_KEY(), JSON.stringify(list));
  }
  function recent() {
    try { const l = JSON.parse(store.get(RECENT_KEY()) || "[]"); return Array.isArray(l) ? l.filter(g => g && Number.isInteger(g.appid) && typeof g.name === "string") : []; }
    catch (e) { return []; }
  }
  let offKey = "", toastTimer = 0, lastToast = 0;
  const offCovers = new Map();

  async function wakeLaunch(appid, name) {
    if (!confirm("PC aufwecken und „" + name + "“ starten?")) return;
    const msg = $("wakemsg");
    msg.textContent = "Sende Magic Packet …";
    try { await call("POST", "api/steam/games/" + appid + "/launch?wake=true&name=" + encodeURIComponent(name)); msg.textContent = ""; }
    catch (e) { msg.textContent = e.message; }
  }
  async function cancelPending(m) {
    try { await call("DELETE", "api/steam/games/" + m.pending_launch.appid + "/launch"); } catch (e) { /* der Hub meldet den Stand ohnehin gleich */ }
  }
  function paintOfflineGames(m) {
    const list = m.status === "offline" && m.wol_configured && !m.pending_launch ? recent() : [];
    const key = current + "|" + list.map(g => g.appid).join(",");
    $("offgames").hidden = !list.length;
    if (key === offKey) return;
    offKey = key;
    const grid = $("offgames_grid");
    grid.textContent = "";
    for (const g of list) {
      const b = document.createElement("button");
      b.className = "sttile";
      b.title = g.name;
      const frame = document.createElement("div"), img = document.createElement("img"), ph = document.createElement("span"), cap = document.createElement("span");
      frame.className = "stcover"; img.alt = ""; ph.className = "stph"; ph.textContent = g.name;
      cap.className = "gcap"; cap.textContent = g.name;
      frame.append(ph, img); b.append(frame, cap);
      b.onclick = () => wakeLaunch(g.appid, g.name);
      grid.append(b);
      loadArt(img, g.appid, "cover", 200, g.art_ver, offCovers, ok => { if (ok) ph.hidden = true; });   // klappt nur, solange das Bild im Browser-Cache liegt
    }
  }
  function showToast(text, ok) {
    const t = $("launchtoast");
    t.textContent = text; t.className = "toast" + (ok === false ? " bad" : ok ? " good" : ""); t.hidden = false;
    clearTimeout(toastTimer);
    if (ok != null) toastTimer = setTimeout(() => { t.hidden = true; }, 14000);
  }
  window.addEventListener("pcc:state", e => {
    const m = e.detail, p = m.pending_launch, r = m.launch_result;
    const wake = $("wakepending"), off = $("offpending");
    wake.hidden = !(p && m.status === "waking");
    off.hidden = !(p && m.status === "offline");
    for (const [el, txt] of [[wake, "wakepending_txt"], [off, "offpending_txt"]]) if (!el.hidden) $(txt).textContent = "Startet danach: " + p.name;
    paintOfflineGames(m);
    if (p && m.status === "online") showToast("Startet gleich: " + p.name + " …", null);
    else if (r && r.at !== lastToast) { lastToast = r.at; showToast(r.ok ? "„" + r.name + "“ gestartet." : "„" + r.name + "“ nicht gestartet: " + r.message, r.ok); }
    else if (!p && $("launchtoast").className === "toast") $("launchtoast").hidden = true;
    window.__pendingMsg = m;
  });
  $("wakepending_cancel").onclick = () => window.__pendingMsg && cancelPending(window.__pendingMsg);
  $("offpending_cancel").onclick = () => window.__pendingMsg && cancelPending(window.__pendingMsg);
  $("launchtoast").onclick = () => { $("launchtoast").hidden = true; };

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
  new MutationObserver(dlWatch).observe(view, { attributes: true, attributeFilter: ["hidden"] });
})();
