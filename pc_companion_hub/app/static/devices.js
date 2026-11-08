"use strict";
// Geräte & Anmeldung (Tab „Steuerung“): gekoppelte Geräte, QR-Kopplung, Abmelden.
(function () {
  const $ = id => document.getElementById(id);
  const msg = t => { $("dev_msg").textContent = t || ""; };
  const inIngress = location.pathname.includes("/hassio_ingress/");
  const ownBase = () => location.origin + location.pathname.replace(/[^/]*$/, "");
  let current = null, kind = "", publicUrl = "", countdown = null, poll = null, baseTimer = null, knownCount = 0;

  async function api(path, method, body) {
    const r = await fetch(path, {
      method: method || "GET",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }

  function ago(ts) {
    if (!ts) return "–";
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 90) return "gerade eben";
    if (s < 3600) return "vor " + Math.round(s / 60) + " Min.";
    if (s < 86400) return "vor " + Math.round(s / 3600) + " Std.";
    return "vor " + Math.round(s / 86400) + " Tagen";
  }

  function render(list) {
    knownCount = list.length;
    const box = $("dev_list");
    box.textContent = "";
    if (!list.length) { box.textContent = "Noch kein Gerät gekoppelt."; box.className = "muted"; return; }
    box.className = "";
    for (const d of list) {
      const row = document.createElement("div");
      row.className = "devrow";
      const info = document.createElement("div");
      const name = document.createElement("b");
      name.textContent = d.name;
      info.append(name);
      if (d.id === current) {
        const me = document.createElement("span");
        me.className = "me";
        me.textContent = "dieses Gerät";
        info.append(" ", me);
      }
      const sub = document.createElement("small");
      sub.className = "muted";
      const rl = document.createElement("span");
      rl.className = "devrole r-" + (d.role || "full");
      rl.textContent = d.role === "view" ? "nur ansehen" : "Vollzugriff";
      sub.append(rl, " · zuletzt " + ago(d.last_seen));
      info.append(document.createElement("br"), sub);
      const btns = document.createElement("div");
      btns.className = "devbtns2";
      if (role === "full") {
        const rb = document.createElement("button");
        rb.textContent = d.role === "view" ? "Vollzugriff geben" : "Nur ansehen";
        rb.onclick = () => setRole(d, d.role === "view" ? "full" : "view");
        btns.append(rb);
      }
      const del = document.createElement("button");
      del.textContent = "Entfernen";
      del.onclick = () => remove(d);
      btns.append(del);
      row.append(info, btns);
      box.append(row);
    }
  }

  async function load() {
    try {
      const d = await api("api/devices");
      current = d.current; kind = d.kind; publicUrl = d.public_url || "";
      render(d.devices);
      $("logout_btn").hidden = kind === "ingress";
      msg("");
    } catch (e) { msg(e.message); }
  }

  async function setRole(d, newRole) {
    try {
      await api("api/devices/" + encodeURIComponent(d.id), "PATCH", { role: newRole });
      load();
    } catch (e) { msg(e.message); }
  }

  async function remove(d) {
    if (!confirm(d.id === current ? "Dieses Gerät abmelden?" : "„" + d.name + "“ entfernen? Es muss sich danach neu anmelden.")) return;
    try {
      await api("api/devices/" + encodeURIComponent(d.id), "DELETE");
      if (d.id === current) { clearLocal(); location.reload(); return; }
      load();
    } catch (e) { msg(e.message); }
  }

  function clearLocal() {
    store.set("pcc_ui_token", "");
    store.set("pcc_device_id", "");
  }

  $("logout_btn").onclick = async () => {
    if (!confirm("Auf diesem Gerät abmelden?")) return;
    try { if (current) await api("api/devices/" + encodeURIComponent(current), "DELETE"); } catch (e) { /* trotzdem lokal abmelden */ }
    clearLocal();
    location.reload();
  };

  /* ---- QR-Kopplung ---- */
  function defaultBase() {
    return store.get("pcc_pair_base") || (inIngress ? publicUrl : ownBase()) || "";
  }

  function stopPair() {
    clearInterval(countdown); clearInterval(poll);
    $("pair_box").hidden = true;
  }

  async function startPair() {
    const base = $("pair_base").value.trim();
    if (!base) { $("pair_hint").textContent = "Adresse eintragen, unter der das Handy den Hub erreicht, z. B. http://192.168.1.10:8099"; $("pair_qr").hidden = true; return; }
    try {
      const d = await api("api/pair", "POST", { base, role: $("pair_role").value });
      store.set("pcc_pair_base", base);
      $("pair_hint").textContent = "";
      $("pair_qr").hidden = !d.qr;
      if (d.qr) $("pair_qr").src = d.qr;
      $("pair_url").textContent = d.url;
      let left = d.expires_s;
      clearInterval(countdown); clearInterval(poll);
      const tick = () => {
        $("pair_left").textContent = Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
        if (left-- <= 0) { stopPair(); msg("Code abgelaufen. Neu erzeugen."); }
      };
      tick(); countdown = setInterval(tick, 1000);
      const before = knownCount;
      poll = setInterval(async () => {
        try {
          const l = await api("api/devices");
          if (l.devices.length > before) { stopPair(); render(l.devices); msg("Gerät gekoppelt ✓"); }
        } catch (e) { /* nächster Versuch */ }
      }, 3000);
    } catch (e) { $("pair_hint").textContent = e.message; }
  }

  $("pair_btn").onclick = () => {
    msg("");
    $("pair_box").hidden = false;
    $("pair_base").value = defaultBase();
    startPair();
  };
  $("pair_base").oninput = () => { clearTimeout(baseTimer); baseTimer = setTimeout(startPair, 700); };
  $("pair_role").onchange = startPair;
  $("pair_close").onclick = stopPair;

  /* ---- Protokoll ---- */
  async function loadAudit() {
    const box = $("audit_list");
    try {
      const d = await api("api/audit?limit=30");
      box.textContent = "";
      box.className = "";
      if (!d.entries.length) { box.textContent = "Noch nichts protokolliert."; box.className = "muted"; return; }
      for (const e of d.entries) {
        const row = document.createElement("div");
        row.className = "auditrow" + (e.ok ? "" : " bad");
        const t = new Date(e.t * 1000);
        const b = document.createElement("b");
        b.textContent = e.what;
        const sm = document.createElement("small");
        sm.textContent = t.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
          + " · " + e.who + (e.pc ? " · " + e.pc : "") + (e.detail ? " · " + e.detail : "");
        row.append(b, sm);
        box.append(row);
      }
    } catch (e) { box.textContent = e.message; }
  }
  $("audit_reload").onclick = loadAudit;

  // Liste laden, sobald der Tab „Steuerung“ sichtbar wird
  const view = document.querySelector('[data-view="ctrl"]');
  new MutationObserver(() => { if (!view.hidden) { load(); loadAudit(); } }).observe(view, { attributes: true, attributeFilter: ["hidden"] });
  if (!view.hidden) { load(); loadAudit(); }
})();
