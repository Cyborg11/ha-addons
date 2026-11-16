"use strict";
// Fernbedienung light (Phase 10.10): Touchpad und Tasten, nur innerhalb einer zeitlich begrenzten Sitzung. Alle Prüfungen macht Hub und Agent.
(function () {
  const $ = id => document.getElementById(id);
  let open = false, timer = 0, leftS = 0, polling = 0;
  let sx = 0, sy = 0, lx = 0, ly = 0, t0 = 0, moved = 0, pend = { dx: 0, dy: 0 }, flushT = 0, down = false;

  async function call(method, path, body) {
    const r = await fetch(pcq(path), { method, headers: { ...authHeaders(), "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(d.detail || ("Fehler " + r.status)); e.status = r.status; throw e; }
    return d;
  }
  const send = body => call("POST", "api/remote/input", body).catch(e => { if (e.status === 403) end("Die Sitzung ist beendet."); else $("rc_msg").textContent = e.message; });

  let viewTimer = 0, viewBusy = false, viewUrl = null;
  function stopView() {
    clearInterval(viewTimer); viewTimer = 0;
    if (viewUrl) { URL.revokeObjectURL(viewUrl); viewUrl = null; }
    $("rc_pad").style.backgroundImage = "";
    $("rc_pad").classList.remove("hasimg");
  }
  async function pullView() {
    if (viewBusy || document.hidden || !open) return;
    viewBusy = true;
    try {
      const r = await fetch(pcq("api/screenshot?width=900&live=1"), { headers: authHeaders() });
      if (r.ok && $("rc_view").checked && open) {
        const u = URL.createObjectURL(await r.blob());
        $("rc_pad").style.backgroundImage = "url(" + u + ")";
        $("rc_pad").classList.add("hasimg");
        if (viewUrl) URL.revokeObjectURL(viewUrl);
        viewUrl = u;
      }
    } catch (e) { /* nächster Versuch in 2 s */ }
    viewBusy = false;
  }
  $("rc_view").onchange = () => { stopView(); if ($("rc_view").checked && open) { pullView(); viewTimer = setInterval(pullView, 2000); } };

  function show(on) {
    open = on;
    if (!on) { stopView(); $("rc_view").checked = false; }
    $("rc_live").hidden = !on;
    $("rc_start_box").hidden = on;
    clearInterval(timer); clearInterval(polling);
    if (on) {
      timer = setInterval(() => { leftS = Math.max(0, leftS - 1); paintLeft(); if (leftS <= 0) end("Die Sitzung ist abgelaufen."); }, 1000);
      polling = setInterval(async () => { try { const s = await call("GET", "api/remote"); if (!s.open) end("Die Sitzung ist beendet."); else leftS = s.left_s; } catch (e) { /* kurz weg: der Zähler läuft weiter */ } }, 15000);
    }
  }
  function paintLeft() { $("rc_left").textContent = "Sitzung: noch " + Math.floor(leftS / 60) + ":" + String(leftS % 60).padStart(2, "0"); }
  function end(msg) { if (open) show(false); $("rc_msg").textContent = msg || ""; }

  $("rc_start").onclick = async () => {
    $("rc_msg").textContent = "";
    try {
      const d = await call("POST", "api/remote/session", { minutes: 5 });
      leftS = d.left_s || 300; paintLeft(); show(true);
    } catch (e) { $("rc_msg").textContent = e.status === 428 ? "PIN erforderlich." : e.message; }
  };
  $("rc_stop").onclick = async () => { try { await call("DELETE", "api/remote/session"); } catch (e) { /* der Hub beendet sie ohnehin */ } end("Sitzung beendet."); };
  document.querySelectorAll("#rc_live [data-rc]").forEach(b => { b.onclick = () => { try { send(JSON.parse(b.dataset.rc)); } catch (e) { /* ungültiges Attribut */ } }; });
  $("rc_send").onclick = async () => {
    const v = $("rc_text").value;
    if (!v) return;
    await send({ type: "text", text: v });
    $("rc_text").value = "";
  };
  $("rc_text").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); $("rc_send").click(); } };

  /* Touchpad: ziehen bewegt (gebündelt, höchstens etwa 25 Mal pro Sekunde), kurzes Tippen klickt */
  function flush() {
    flushT = 0;
    const dx = Math.round(pend.dx), dy = Math.round(pend.dy);
    if (!dx && !dy) return;
    pend = { dx: 0, dy: 0 };
    send({ type: "move", dx, dy });
  }
  const pad = $("rc_pad");
  pad.addEventListener("pointerdown", e => { down = true; pad.setPointerCapture(e.pointerId); sx = lx = e.clientX; sy = ly = e.clientY; t0 = Date.now(); moved = 0; e.preventDefault(); });
  pad.addEventListener("pointermove", e => {
    if (!down) return;
    const dx = e.clientX - lx, dy = e.clientY - ly;
    lx = e.clientX; ly = e.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    pend.dx += dx * 1.6; pend.dy += dy * 1.6;                          // etwas schneller als der Finger
    if (!flushT) flushT = setTimeout(flush, 40);
  });
  const up = () => {
    if (!down) return;
    down = false;
    if (moved < 8 && Date.now() - t0 < 300) send({ type: "click", button: "left" });
    else flush();
  };
  pad.addEventListener("pointerup", up);
  pad.addEventListener("pointercancel", () => { down = false; });

  async function check() {
    try {
      const s = await call("GET", "api/remote");
      $("rc_start").disabled = !s.available;
      $("rc_hint").textContent = !s.pin_set ? "Dafür muss im Add-on eine Sicherheits-PIN (confirm_pin) gesetzt sein." : "Dafür ist die Sicherheits-PIN nötig. Die Sitzung endet von selbst.";
      if (s.open && !open) { leftS = s.left_s; paintLeft(); show(true); }
    } catch (e) { /* Karte bleibt, wie sie ist */ }
  }
  window.addEventListener("pcc:features", () => { if (!$("remotepanel").hidden) check(); });
  window.addEventListener("pcc:pc", () => { if (open) show(false); });
})();
