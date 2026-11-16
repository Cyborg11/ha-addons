"use strict";
// Dateibrowser (Phase 10.9): Ordner am PC ansehen, Dateien laden. Nur lesend; der Agent entscheidet, was freigegeben ist.
(function () {
  const $ = id => document.getElementById(id);
  let folder = null, path = "", loadedPc = null, seq = 0;
  const fmt = b => b == null ? "" : b >= 1e9 ? (b / 1e9).toFixed(1).replace(".", ",") + " GB" : b >= 1e6 ? (b / 1e6).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB";
  const IMG = /\.(png|jpe?g|gif|webp)$/i;

  async function api(url, asBlob) {
    const r = await fetch(pcq(url), { headers: authHeaders() });
    if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || ("Fehler " + r.status)); }
    return asBlob ? r.blob() : r.json();
  }
  const q = o => Object.entries(o).filter(([, v]) => v != null && v !== "").map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");

  function save(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.append(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }
  async function getFile(it, dl) {
    const msg = $("br_msg");
    msg.textContent = "Lädt „" + it.name + "“ …";
    try {
      const rel = (path ? path + "/" : "") + it.name;
      const blob = await api("api/browse/file?" + q({ folder, path: rel, download: dl ? "true" : "" }), true);
      msg.textContent = "";
      if (!dl && IMG.test(it.name) && window.openViewer) window.openViewer({ blob, title: it.name, filename: it.name });
      else save(blob, it.name);
    } catch (e) { msg.textContent = e.message; }
  }

  function paint(d) {
    const list = $("br_list");
    list.textContent = "";
    folder = d.folder;
    path = d.path || "";
    $("br_path").textContent = (folder ? folder + "/" : "") + path;
    $("br_up").disabled = !folder;
    for (const it of d.items) {
      const row = document.createElement("div"), name = document.createElement("button"), meta = document.createElement("small");
      row.className = "mh"; name.type = "button"; name.className = "linkbtn";
      name.textContent = (it.dir ? "📁 " : "") + it.name;
      meta.className = "muted"; meta.textContent = it.dir ? "" : fmt(it.size);
      if (it.dir) name.onclick = () => d.folder == null ? open(it.name, "") : open(d.folder, (d.path ? d.path + "/" : "") + it.name);
      else name.onclick = () => getFile(it, false);
      row.append(name, meta);
      if (!it.dir) {
        const dl = document.createElement("button"); dl.type = "button"; dl.textContent = "Laden"; dl.onclick = () => getFile(it, true); row.append(dl);
      }
      list.append(row);
    }
    if (!d.items.length) { const p = document.createElement("div"); p.className = "muted"; p.textContent = "Leer."; list.append(p); }
    if (d.truncated) { const p = document.createElement("div"); p.className = "muted"; p.textContent = "Nur die ersten " + d.items.length + " von " + d.total + " Einträgen."; list.append(p); }
  }
  async function open(f, p) {
    const my = ++seq;
    $("br_msg").textContent = "";
    try {
      const d = await api("api/browse?" + q({ folder: f, path: p }));
      if (my === seq) paint(d);
    } catch (e) { if (my === seq) $("br_msg").textContent = e.message; }
  }
  $("br_up").onclick = () => {
    if (!path) return open(null, "");                    // oberste Ebene: zurück zur Ordnerauswahl (bei nur einem Ordner bleibt es dort)
    open(folder, path.split("/").slice(0, -1).join("/"));
  };
  function maybeLoad() {
    if ($("browsebox").hidden || loadedPc === current) return;
    loadedPc = current; folder = null; path = "";
    open(null, "");
  }
  window.addEventListener("pcc:features", maybeLoad);
  window.addEventListener("pcc:pc", () => { loadedPc = null; seq++; $("br_list").textContent = ""; $("br_msg").textContent = ""; });
  window.addEventListener("pcc:state", maybeLoad);
})();
