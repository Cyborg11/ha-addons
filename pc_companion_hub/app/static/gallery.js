"use strict";
// Galerie-Tab (neueste Bilder der Ausgabeordner) und der gemeinsame Bildbetrachter (Galerie, Screenshot).
(function () {
  const $ = id => document.getElementById(id);
  const PAGE = 24;
  let folder = "", folders = [], items = [], total = 0, loading = false, loadedPc = "", loadedAt = 0;
  const thumbs = new Map();                 // Bildname -> Blob-URL (damit Bilder nicht doppelt geladen werden)
  let viewerUrl = null;

  async function getJson(path) {
    const r = await fetch(pcq(path), { headers: authHeaders() });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }

  /* ---- Betrachter ---- */
  window.openViewer = function ({ blob, title, filename, load }) {
    const v = $("viewer");
    if (viewerUrl) { URL.revokeObjectURL(viewerUrl); viewerUrl = null; }
    v.hidden = false;
    $("viewer_title").textContent = title || "";
    $("viewer_img").removeAttribute("src");
    const show = b => { viewerUrl = URL.createObjectURL(b); $("viewer_img").src = viewerUrl; $("viewer_save").onclick = () => saveBlob(b, filename || "bild.png"); };
    if (blob) show(blob);
    else if (load) { $("viewer_title").textContent = (title || "") + " – lädt …"; load().then(b => { $("viewer_title").textContent = title || ""; show(b); }).catch(e => { $("viewer_title").textContent = e.message; }); }
  };
  function closeViewer() {
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
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("viewer").hidden) closeViewer(); });

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

  function addTiles(list) {
    const grid = $("gal_grid");
    for (const it of list) {
      const b = document.createElement("button");
      b.className = "gtile";
      b.title = it.name;
      const img = document.createElement("img");
      img.alt = it.name;
      b.append(img);
      b.onclick = () => openViewer({
        title: it.name.split("/").pop(), filename: it.name.split("/").pop(),
        load: () => fetchBlob("api/gallery/file?" + q({ folder, name: it.name })),
      });
      grid.append(b);
      loadThumb(img, it.name);
    }
  }

  async function load(reset) {
    if (loading || !features.includes("gallery")) return;
    loading = true;
    $("gal_msg").textContent = "";
    try {
      if (reset) { items = []; $("gal_grid").textContent = ""; }
      const d = await getJson("api/gallery?" + q({ folder, limit: PAGE, offset: items.length }));
      folders = d.folders; folder = d.folder; total = d.total;
      items = items.concat(d.items);
      addTiles(d.items);
      loadedPc = current; loadedAt = Date.now();
      const sel = $("gal_folder");
      sel.hidden = folders.length < 2;
      if (sel.options.length !== folders.length) { sel.textContent = ""; for (const f of folders) sel.append(new Option(f, f)); }
      sel.value = folder;
      $("gal_more").hidden = items.length >= total;
      $("gal_count").textContent = total ? items.length + " von " + total + " Bildern" : "Keine Bilder gefunden.";
    } catch (e) { $("gal_msg").textContent = e.message; }
    loading = false;
  }

  $("gal_more").onclick = () => load(false);
  $("gal_reload").onclick = () => load(true);
  $("gal_folder").onchange = () => { folder = $("gal_folder").value; load(true); };
  window.addEventListener("pcc:pc", () => {
    folder = ""; folders = []; loadedPc = ""; $("gal_grid").textContent = ""; $("gal_folder").textContent = "";
    thumbs.forEach(u => URL.revokeObjectURL(u)); thumbs.clear();
  });

  const view = document.querySelector('[data-view="gallery"]');
  new MutationObserver(() => { if (!view.hidden && (loadedPc !== current || Date.now() - loadedAt > 30000)) load(true); })
    .observe(view, { attributes: true, attributeFilter: ["hidden"] });
})();
