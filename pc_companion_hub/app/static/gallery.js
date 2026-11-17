"use strict";
// Galerie-Tab (neueste Bilder der Ausgabeordner) und der gemeinsame Bildbetrachter (Galerie, Screenshot).
(function () {
  const $ = id => document.getElementById(id);
  const PAGE = 24;
  let folder = "", game = "", games = [], folders = [], items = [], total = 0, loading = false, loadedPc = "", loadedAt = 0;
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
  let sx = null;
  $("viewer").addEventListener("touchstart", e => { sx = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
  $("viewer").addEventListener("touchend", e => {
    if (sx == null) return;
    const dx = e.changedTouches[0].clientX - sx; sx = null;
    if (Math.abs(dx) > 60) step(dx > 0 ? -1 : 1);
  }, { passive: true });
  function closeViewer() {
    vseq++; vnav = null;
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
    const all = games.reduce((n, g) => n + g.count, 0);
    sel.append(new Option("Alle Spiele (" + all + ")", ""));
    for (const g of games) sel.append(new Option(g.name + " (" + g.count + ")", g.appid));
    sel.value = game;
  }

  async function load(reset) {
    if (loading || !features.includes("gallery")) return;
    loading = true;
    $("gal_msg").textContent = "";
    try {
      if (reset) { items = []; $("gal_grid").textContent = ""; }
      const d = await getJson("api/gallery?" + q({ folder, game, limit: PAGE, offset: items.length }));
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
    } catch (e) { $("gal_msg").textContent = e.message; }
    loading = false;
  }

  $("gal_more").onclick = () => load(false);
  $("gal_reload").onclick = () => load(true);
  $("gal_folder").onchange = () => { folder = $("gal_folder").value; game = ""; load(true); };
  $("gal_game").onchange = () => { game = $("gal_game").value; load(true); };
  window.addEventListener("pcc:pc", () => {
    folder = ""; game = ""; games = []; folders = []; loadedPc = ""; $("gal_grid").textContent = ""; $("gal_folder").textContent = "";
    thumbs.forEach(u => URL.revokeObjectURL(u)); thumbs.clear();
  });

  const view = document.querySelector('[data-view="gallery"]');
  new MutationObserver(() => { if (!view.hidden && (loadedPc !== current || Date.now() - loadedAt > 30000)) load(true); })
    .observe(view, { attributes: true, attributeFilter: ["hidden"] });
})();
