"use strict";
// Galerie-Tab (neueste Bilder der Ausgabeordner) und der gemeinsame Bildbetrachter (Galerie, Screenshot).
(function () {
  const $ = id => document.getElementById(id);
  const PAGE = 24;
  let folder = "", game = "", sort = (store.get("pcc_gsort") === "asc" ? "asc" : "desc"), games = [], folders = [], items = [], total = 0, loading = false, loadedPc = "", loadedAt = 0;
  const thumbs = new Map();                 // Bildname -> Blob-URL (damit Bilder nicht doppelt geladen werden)
  let viewerUrl = null;

  async function getJson(path) {
    const r = await fetch(pcq(path), { headers: authHeaders() });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }

  /* ---- Betrachter ---- */
  let vseq = 0, vnav = null;
  // nav (optional): { pos, total, prev(), next() } – Pfeile, Tastatur und Wischen blättern durch die Galerie
  window.openViewer = function ({ blob, title, info, filename, load, nav }) {
    const v = $("viewer"), my = ++vseq;
    if (viewerUrl) { URL.revokeObjectURL(viewerUrl); viewerUrl = null; }
    v.hidden = false;
    vnav = nav || null;
    $("viewer_prev").hidden = !(nav && nav.prev);
    $("viewer_next").hidden = !(nav && nav.next);
    $("viewer_pos").textContent = nav ? nav.pos + " / " + nav.total : "";
    $("viewer_title").textContent = title || "";
    $("viewer_info").textContent = info || "";
    $("viewer_img").removeAttribute("src");
    resetZoom();
    const show = b => { if (my !== vseq) return; viewerUrl = URL.createObjectURL(b); $("viewer_img").src = viewerUrl; $("viewer_save").onclick = () => saveBlob(b, filename || "bild.png"); };
    if (blob) show(blob);
    else if (load) {
      $("viewer_title").textContent = (title || "") + " – lädt …";
      load().then(b => { if (my !== vseq) return; $("viewer_title").textContent = title || ""; show(b); }).catch(e => { if (my === vseq) $("viewer_title").textContent = e.message; });
    }
  };
  const step = d => { const f = vnav && (d < 0 ? vnav.prev : vnav.next); if (f) f(); };
  $("viewer_prev").onclick = () => step(-1);
  $("viewer_next").onclick = () => step(1);
  /* Zoom: Zwei-Finger-Pinch, Doppeltipp, Mausrad, Knöpfe +/−; verschieben per Ziehen; bei 1× wischen = blättern; Vollbild blendet die Leisten aus */
  const MAXZ = 8;
  let zs = 1, zx = 0, zy = 0;
  const ptrs = new Map();
  let drag = null, pinch = null, lastTap = 0, tapTimer = 0;
  const vimg = $("viewer_img"), vstage = document.querySelector("#viewer .vstage");
  function applyZoom() {
    const w = vstage.clientWidth, h = vstage.clientHeight;
    const mx = Math.max(0, (zs - 1) * w / 2), my = Math.max(0, (zs - 1) * h / 2);
    zx = Math.max(-mx, Math.min(mx, zx)); zy = Math.max(-my, Math.min(my, zy));
    vimg.style.transform = zs === 1 ? "" : "translate(" + zx + "px," + zy + "px) scale(" + zs + ")";
    vstage.classList.toggle("zoomed", zs > 1);
    $("viewer_zoomout").disabled = zs <= 1; $("viewer_zoomin").disabled = zs >= MAXZ;
  }
  function resetZoom() { zs = 1; zx = zy = 0; ptrs.clear(); drag = pinch = null; applyZoom(); }
  // Zoom um einen Punkt (Bildschirm-Koordinaten), damit der Punkt unter dem Finger bleibt
  function zoomAt(ns, cx, cy) {
    ns = Math.max(1, Math.min(MAXZ, ns));
    const r = vstage.getBoundingClientRect(), px = cx - (r.left + r.width / 2), py = cy - (r.top + r.height / 2), k = ns / zs;
    zx = px - (px - zx) * k; zy = py - (py - zy) * k; zs = ns;
    if (zs === 1) zx = zy = 0;
    applyZoom();
  }
  function setClean(on) {
    $("viewer").classList.toggle("vclean", on);
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  function toggleFull() {
    const v = $("viewer"), on = !v.classList.contains("vclean");
    setClean(on);
    if (on && v.requestFullscreen) v.requestFullscreen().catch(() => {});
  }
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) $("viewer").classList.remove("vclean"); });
  $("viewer_full").onclick = toggleFull;
  $("viewer_zoomin").onclick = () => { const r = vstage.getBoundingClientRect(); zoomAt(zs * 1.6, r.left + r.width / 2, r.top + r.height / 2); };
  $("viewer_zoomout").onclick = () => { const r = vstage.getBoundingClientRect(); zoomAt(zs / 1.6, r.left + r.width / 2, r.top + r.height / 2); };
  vstage.addEventListener("wheel", e => { e.preventDefault(); zoomAt(zs * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX, e.clientY); }, { passive: false });
  vstage.addEventListener("pointerdown", e => {
    if (e.target.closest(".vnav")) return;
    vstage.setPointerCapture(e.pointerId);
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: zs }; drag = null;
    } else if (ptrs.size === 1) drag = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, moved: false };
  });
  vstage.addEventListener("pointermove", e => {
    const p = ptrs.get(e.pointerId); if (!p) return;
    p.x = e.clientX; p.y = e.clientY;
    if (pinch && ptrs.size >= 2) {
      const [a, b] = [...ptrs.values()];
      zoomAt(pinch.s * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.d), (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (drag) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 8) drag.moved = true;
      if (zs > 1) { zx += e.clientX - drag.x; zy += e.clientY - drag.y; applyZoom(); }
      drag.x = e.clientX; drag.y = e.clientY;
    }
  });
  const endPtr = e => {
    if (!ptrs.has(e.pointerId)) return;
    ptrs.delete(e.pointerId);
    if (pinch) {
      if (ptrs.size < 2) { pinch = null; const rest = [...ptrs.values()][0]; drag = rest ? { x: rest.x, y: rest.y, x0: rest.x, y0: rest.y, moved: true } : null; }
      return;
    }
    const d = drag; drag = null;
    if (!d || e.type === "pointercancel") return;
    const dx = e.clientX - d.x0, dy = e.clientY - d.y0;
    if (!d.moved) {                                    // Tippen: zweimal = Zoom umschalten, einmal im Vollbild = Leisten zurück
      const now = Date.now();
      if (now - lastTap < 300) { clearTimeout(tapTimer); lastTap = 0; if (zs > 1) { zs = 1; zx = zy = 0; applyZoom(); } else zoomAt(2.5, e.clientX, e.clientY); }
      else { lastTap = now; clearTimeout(tapTimer); tapTimer = setTimeout(() => { if ($("viewer").classList.contains("vclean")) setClean(false); }, 300); }
    } else if (zs === 1 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx > 0 ? -1 : 1);
  };
  vstage.addEventListener("pointerup", endPtr);
  vstage.addEventListener("pointercancel", endPtr);
  function closeViewer() {
    vseq++; vnav = null;
    setClean(false); resetZoom();
    $("viewer").hidden = true;
    if (viewerUrl) { URL.revokeObjectURL(viewerUrl); viewerUrl = null; }
  }
  function saveBlob(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  $("viewer_close").onclick = closeViewer;
  $("viewer").addEventListener("click", e => { if (e.target === $("viewer")) closeViewer(); });
  document.addEventListener("keydown", e => {
    if ($("viewer").hidden) return;
    if (e.key === "Escape") closeViewer();
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "+" || e.key === "=") $("viewer_zoomin").click();
    else if (e.key === "-") $("viewer_zoomout").click();
    else if (e.key === "0") resetZoom();
    else if (e.key === "f" || e.key === "F") toggleFull();
  });

  /* ---- Galerie ---- */
  const q = o => Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");

  async function fetchBlob(path) {
    const r = await fetch(pcq(path), { headers: authHeaders() });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ("Fehler " + r.status));
    return r.blob();
  }

  // Vorschaubilder höchstens 4 gleichzeitig laden
  let active = 0;
  const queue = [];
  function pump() {
    while (active < 4 && queue.length) {
      const job = queue.shift();
      active++;
      job().finally(() => { active--; pump(); });
    }
  }
  function loadThumb(img, name) {
    const key = current + "|" + folder + "/" + name;
    if (thumbs.has(key)) { img.src = thumbs.get(key); return; }
    queue.push(async () => {
      try {
        const url = URL.createObjectURL(await fetchBlob("api/gallery/thumb?" + q({ folder, name, w: 320 })));
        thumbs.set(key, url); img.src = url;
      } catch (e) { img.alt = "?"; }
    });
    pump();
  }

  const fmtSize = n => n >= 1048576 ? (n / 1048576).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  const fmtDate = t => new Date(t * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

  function openAt(i) {
    const it = items[i], name = it.name.split("/").pop();
    openViewer({
      title: it.game || (folder === "steam-profile" ? "Steam-Profil" : name), filename: name,
      info: [it.mtime ? fmtDate(it.mtime) : "", it.size ? fmtSize(it.size) : "", it.game ? name : "", it.online && folder !== "steam-profile" ? "☁ auf dem Steam-Profil" : ""].filter(Boolean).join(" · "),
      load: () => fetchBlob("api/gallery/file?" + q({ folder, name: it.name })),
      nav: {
        pos: i + 1, total,
        prev: i > 0 ? () => openAt(i - 1) : null,
        next: i < items.length - 1 ? () => openAt(i + 1)
          : (items.length < total ? async () => { await load(false); if (i + 1 < items.length) openAt(i + 1); } : null),
      },
    });
    for (const j of [i + 1, i - 1]) if (items[j]) fetchBlob("api/gallery/file?" + q({ folder, name: items[j].name })).catch(() => {});   // Nachbarn schon laden
  }

  function addTiles(list, base) {
    const grid = $("gal_grid");
    list.forEach((it, k) => {
      const idx = base + k, label = it.name.split("/").pop().replace(/\.[^.]+$/, "");
      const b = document.createElement("button");
      b.className = "gtile";
      b.title = (it.game ? it.game + " – " : "") + it.name;
      const img = document.createElement("img");
      img.alt = it.name;
      const cap = document.createElement("span");
      cap.className = "gcap";
      cap.textContent = folder === "steam-profile" ? "Auf dem Profil" : (it.game || label);
      if (it.online && folder !== "steam-profile") {                   // schon auf dem Steam-Profil: kleine Wolke unten links
        const cl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        cl.setAttribute("viewBox", "0 0 24 24"); cl.setAttribute("class", "gcloud");
        cl.innerHTML = '<title>Auf dem Steam-Profil</title><path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 17.9 10 4 4 0 0 1 17.5 18z"/>';
        b.append(cl);
        cap.style.paddingLeft = "26px";
      }
      b.append(img, cap);
      b.onclick = () => openAt(idx);
      grid.append(b);
      loadThumb(img, it.name);
    });
  }

  // Wenige Ordner als Schalter, viele als Auswahlliste
  function paintFolders() {
    const chips = $("gal_chips"), sel = $("gal_folder"), few = folders.length >= 2 && folders.length <= 6;
    chips.hidden = !few; sel.hidden = few || folders.length < 2;
    chips.textContent = "";
    if (few) for (const f of folders) {
      const b = document.createElement("button");
      b.className = "segbtn" + (f === folder ? " on" : ""); b.textContent = f;
      b.onclick = () => { folder = f; game = ""; load(true); };
      chips.append(b);
    }
  }

  // Spielfilter wie bei den Steam-Screenshots (nur der Steam-Ordner liefert eine Spieleliste)
  function paintGames() {
    const sel = $("gal_game");
    sel.hidden = games.length < 2;
    sel.textContent = "";
    const counted = games.every(g => g.count != null);      // das Profil kennt keine Anzahl je Spiel
    sel.append(new Option(counted ? "Alle Spiele (" + games.reduce((n, g) => n + g.count, 0) + ")" : "Alle Spiele", ""));
    for (const g of games) sel.append(new Option(counted ? g.name + " (" + g.count + ")" : g.name, g.appid));
    sel.value = game;
  }

  async function load(reset) {
    if (loading || !features.includes("gallery")) return;
    loading = true;
    $("gal_msg").textContent = "";
    try {
      if (reset) { items = []; $("gal_grid").textContent = ""; }
      const d = await getJson("api/gallery?" + q({ folder, game, sort: sort === "asc" ? "asc" : "", limit: PAGE, offset: items.length }));
      folders = d.folders; folder = d.folder; total = d.total;
      if (d.games) games = d.games; else { games = []; game = ""; }
      const base = items.length;
      items = items.concat(d.items);
      addTiles(d.items, base);
      loadedPc = current; loadedAt = Date.now();
      const sel = $("gal_folder");
      paintFolders();
      paintGames();
      if (sel.options.length !== folders.length) { sel.textContent = ""; for (const f of folders) sel.append(new Option(f, f)); }
      sel.value = folder;
      $("gal_more").hidden = items.length >= total;
      $("gal_count").textContent = total ? items.length + " von " + total + " Bildern" : "Keine Bilder gefunden.";
      const ar = d.archive;                                   // Steam-Archiv: Fortschritt des Hintergrund-Downloads
      if (ar) $("gal_msg").textContent = ar.error && !ar.complete ? "Archiv: " + ar.downloaded + " von " + ar.total + " geladen – " + ar.error
        : ar.complete ? "Archiv vollständig: " + ar.downloaded + " Screenshots" : "Archiv lädt im Hintergrund: " + ar.downloaded + " von " + ar.total;
    } catch (e) { $("gal_msg").textContent = e.message; }
    loading = false;
  }

  $("gal_more").onclick = () => load(false);
  $("gal_reload").onclick = () => load(true);
  $("gal_folder").onchange = () => { folder = $("gal_folder").value; game = ""; load(true); };
  $("gal_game").onchange = () => { game = $("gal_game").value; load(true); };
  $("gal_sort").value = sort;
  $("gal_sort").onchange = () => { sort = $("gal_sort").value === "asc" ? "asc" : "desc"; store.set("pcc_gsort", sort); load(true); };
  window.addEventListener("pcc:pc", () => {
    folder = ""; game = ""; games = []; folders = []; loadedPc = ""; $("gal_grid").textContent = ""; $("gal_folder").textContent = "";
    thumbs.forEach(u => URL.revokeObjectURL(u)); thumbs.clear();
  });

  const view = document.querySelector('[data-view="gallery"]');
  new MutationObserver(() => { if (!view.hidden && (loadedPc !== current || Date.now() - loadedAt > 30000)) load(true); })
    .observe(view, { attributes: true, attributeFilter: ["hidden"] });
})();
