"use strict";
// Dateitransfer: Handy -> PC/NAS. XHR (wegen Upload-Fortschritt), eine Datei nach der anderen.
(function () {
  const $ = id => document.getElementById(id);
  const token = () => { try { return localStorage.getItem("pcc_ui_token") || ""; } catch (e) { return ""; } };
  const SHARE_CACHE = "pcc-share";
  let status = "offline", targetsLoaded = false, flushing = false;

  async function loadTargets() {
    if (targetsLoaded) return;
    try {
      const r = await fetch(pcq("api/upload/targets"), { headers: { Authorization: "Bearer " + token() } });
      if (!r.ok) return;
      const d = await r.json();
      $("up_target").innerHTML = "";
      for (const t of d.targets) {
        const o = document.createElement("option");
        o.value = t; o.textContent = t; if (t === d.default) o.selected = true;
        $("up_target").appendChild(o);
      }
      $("up_limit").textContent = "max. " + d.max_mb + " MB";
      targetsLoaded = true;
    } catch (e) { /* später erneut */ }
  }

  function row(name) {
    const el = document.createElement("div");
    el.className = "uprow";
    el.innerHTML = '<span class="n"></span><progress max="1" value="0"></progress><span class="s">…</span>';
    el.querySelector(".n").textContent = name;
    $("up_list").prepend(el);
    const p = el.querySelector("progress"), s = el.querySelector(".s");
    return {
      set: f => { p.value = f; s.textContent = Math.round(f * 100) + " %"; },
      done: t => { p.value = 1; s.textContent = "✓ " + t; el.classList.add("ok"); },
      fail: t => { s.textContent = "✗ " + t; el.classList.add("err"); },
    };
  }

  function send(blob, name, target) {
    return new Promise(resolve => {
      const r = row(name), x = new XMLHttpRequest();
      let url = pcq("api/upload?filename=" + encodeURIComponent(name));
      if (target) url += "&target=" + encodeURIComponent(target);
      x.open("POST", url);
      x.setRequestHeader("Authorization", "Bearer " + token());
      x.setRequestHeader("Content-Type", "application/octet-stream");
      x.upload.onprogress = e => { if (e.lengthComputable) r.set(e.loaded / e.total); };
      x.onload = () => {
        let d = {};
        try { d = JSON.parse(x.responseText); } catch (e) {}
        if (x.status === 200) { r.done(d.filename || name); resolve(true); }
        else { r.fail(d.detail || "Fehler " + x.status); resolve(false); }
      };
      x.onerror = () => { r.fail("Verbindung abgebrochen"); resolve(false); };
      x.send(blob);
    });
  }

  async function sendAll(files) {
    const target = $("up_target").value;
    for (const f of files) await send(f, f.name, target);
  }

  $("up_pick").onclick = () => $("up_files").click();
  $("up_files").onchange = async e => {
    const files = Array.from(e.target.files);
    e.target.value = "";
    if (status !== "online") { $("up_msg").textContent = "PC ist nicht online."; return; }
    $("up_msg").textContent = "";
    await sendAll(files);
  };

  // --- Android-Teilen-Ziel: der Service Worker legt geteilte Dateien im Cache ab ---
  async function flushShared() {
    if (flushing || status !== "online" || !("caches" in window)) return;
    flushing = true;
    try {
      const cache = await caches.open(SHARE_CACHE);
      const keys = await cache.keys();
      if (!keys.length) return;
      await loadTargets();
      $("up_msg").textContent = "";
      for (const req of keys) {
        const res = await cache.match(req);
        const name = decodeURIComponent(res.headers.get("X-Filename") || "upload");
        const ok = await send(await res.blob(), name, $("up_target").value);
        if (ok) await cache.delete(req);
      }
    } catch (e) { /* bleibt im Cache, nächster Versuch bei „online“ */ }
    finally { flushing = false; }
  }

  async function sharedCount() {
    try { return "caches" in window ? (await (await caches.open(SHARE_CACHE)).keys()).length : 0; } catch (e) { return 0; }
  }

  window.addEventListener("pcc:pc", () => { targetsLoaded = false; });   // jeder PC hat eigene Zielordner
  window.addEventListener("pcc:status", async ev => {
    status = ev.detail;
    if (status === "online") { await loadTargets(); flushShared(); }
    else if (await sharedCount()) $("up_msg").textContent = "Geteilte Dateien warten, bis der PC online ist.";
  });

  if (new URLSearchParams(location.search).has("share")) history.replaceState(null, "", location.pathname);
})();
