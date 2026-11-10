"use strict";
// Zusatzfunktionen des Agenten (Phase 8): Energie-Plan, Programme, Prozesse, Zwischenablage, Screenshot, Job-Abbruch und -Verlauf.
// Die Bereiche erscheinen nur, wenn der Agent die Funktion in /health meldet (data-feature im HTML).
(function () {
  const $ = id => document.getElementById(id);

  async function call(path, method, body) {
    const r = await fetch(pcq(path), {
      method: method || "GET",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }

  // Funktion ausführen, wenn eine Ansicht (Tab) sichtbar wird, und danach regelmäßig, solange sie sichtbar ist
  function whileVisible(viewName, fn, everyMs) {
    const view = document.querySelector('[data-view="' + viewName + '"]');
    let timer = null;
    const check = () => {
      clearInterval(timer);
      if (!view.hidden) { fn(); if (everyMs) timer = setInterval(() => { if (!view.hidden && !$("live").hidden) fn(); }, everyMs); }
    };
    new MutationObserver(check).observe(view, { attributes: true, attributeFilter: ["hidden"] });
    window.addEventListener("pcc:pc", () => { if (!view.hidden) fn(); });
    check();
  }

  const row = (cls) => { const d = document.createElement("div"); d.className = cls; return d; };
  const mm = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? h + " Std. " + String(m).padStart(2, "0") + " Min." : m + " Min. " + String(s % 60).padStart(2, "0") + " s"; };
  const MODE = { shutdown: "herunterfahren", sleep: "in den Ruhezustand" };

  /* ---------------- Energie-Plan ---------------- */
  let mode = store.get("pcc_plan_mode") || "shutdown";
  if (!MODE[mode]) mode = "shutdown";

  function renderPlan(p) {
    const parts = [];
    if (p && p.timer) parts.push("PC wird in " + mm(p.timer.left_s) + " " + MODE[p.timer.mode] + ".");
    if (p && p.after_job) {
      const a = p.after_job;
      parts.push(a.waiting_for === "job" ? "Nach dem nächsten KI-Job: " + MODE[a.mode] + " (wartet auf einen Job)."
        : "Nach dem letzten KI-Job: " + MODE[a.mode] + (a.grace_left_s != null ? " – in " + a.grace_left_s + " s, falls kein weiterer Job startet." : " (läuft noch)."));
    }
    $("plan_state").textContent = parts.length ? parts.join(" ") : "Kein Plan aktiv.";
    $("plan_state").className = parts.length ? "planon" : "muted";
    $("plan_cancel").hidden = !parts.length;
    if (p && p.last_error) $("plan_msg").textContent = p.last_error;
  }

  async function setPlan(body, okText) {
    $("plan_msg").textContent = "…";
    try { renderPlan(await call("api/power-plan", "POST", body)); $("plan_msg").textContent = okText; }
    catch (e) { $("plan_msg").textContent = e.message; }
  }

  function renderModeButtons() {
    const box = $("plan_mode");
    box.textContent = "";
    for (const [k, label] of [["shutdown", "Herunterfahren"], ["sleep", "Ruhezustand"]]) {
      const b = document.createElement("button");
      b.className = "segbtn" + (k === mode ? " on" : "");
      b.textContent = label;
      b.onclick = () => { mode = k; store.set("pcc_plan_mode", k); renderModeButtons(); };
      box.append(b);
    }
  }
  renderModeButtons();
  const timerBox = $("plan_timer");
  for (const [min, label] of [[30, "In 30 Min."], [60, "In 1 Std."], [120, "In 2 Std."], [240, "In 4 Std."]]) {
    const b = document.createElement("button");
    b.className = "segbtn";
    b.textContent = label;
    b.onclick = () => setPlan({ timer_minutes: min, mode }, "Timer gesetzt.");
    timerBox.append(b);
  }
  $("plan_afterjob").onclick = () => setPlan({ after_job: mode }, "Wird nach dem letzten KI-Job ausgeführt.");
  $("plan_cancel").onclick = async () => {
    try { renderPlan(await call("api/power-plan", "DELETE")); $("plan_msg").textContent = "Plan abgebrochen."; } catch (e) { $("plan_msg").textContent = e.message; }
  };
  // Stand kommt mit jedem Snapshot (1 Hz), so läuft der Countdown mit
  window.addEventListener("pcc:snap", ev => { if (features.includes("power_plan")) renderPlan(ev.detail.power_plan); });

  /* ---------------- Programme ---------------- */
  async function loadPrograms() {
    if (!features.includes("programs")) return;
    try {
      const d = await call("api/programs");
      const box = $("prog_list");
      box.textContent = "";
      if (!d.programs.length) { box.textContent = "Keine Programme in der config.yaml des Agenten (programs:)."; box.className = "muted"; return; }
      box.className = "";
      for (const p of d.programs) {
        const r = row("devrow");
        const info = document.createElement("div");
        const dot = document.createElement("i");
        dot.className = "dot st-" + (p.running ? "online" : "offline");
        const b = document.createElement("b");
        b.textContent = " " + p.name;
        info.append(dot, b);
        const btn = document.createElement("button");
        btn.textContent = p.running ? "Beenden" : "Starten";
        btn.onclick = async () => {
          if (p.running && !confirm(p.name + " beenden?")) return;
          btn.disabled = true; $("prog_msg").textContent = "…";
          try {
            const res = await call("api/programs/" + encodeURIComponent(p.id) + "/" + (p.running ? "stop" : "start"), "POST");
            $("prog_msg").textContent = res.detail || (p.running ? "Beendet." : "Gestartet.");
          } catch (e) { $("prog_msg").textContent = e.message; }
          setTimeout(loadPrograms, 1500);
        };
        r.append(info, btn);
        box.append(r);
      }
    } catch (e) { $("prog_msg").textContent = e.message; }
  }

  /* ---------------- Prozesse ---------------- */
  let psort = store.get("pcc_psort") || "cpu";
  async function loadProcesses() {
    if (!features.includes("processes") || !$("proc_box").open) return;
    $("proc_sort").querySelectorAll(".segbtn").forEach(b => b.classList.toggle("on", b.dataset.k === psort));
    try {
      const d = await call("api/processes?sort=" + psort + "&limit=12");
      const box = $("proc_list");
      box.textContent = "";
      for (const p of d.processes) {
        const r = row("devrow");
        const info = document.createElement("div");
        const b = document.createElement("b");
        b.textContent = p.name;
        const sm = document.createElement("small");
        sm.className = "muted";
        sm.textContent = "PID " + p.pid + " · CPU " + p.cpu_pct + " % · RAM " + (p.mem_mb ?? "–") + " MB" + (p.vram_mb != null ? " · VRAM " + p.vram_mb + " MB" : "");
        info.append(b, document.createElement("br"), sm);
        r.append(info);
        if (!p.protected) {
          const kill = document.createElement("button");
          kill.textContent = "Beenden";
          kill.onclick = async () => {
            if (!confirm(p.name + " (PID " + p.pid + ") beenden? Ungespeicherte Daten gehen verloren.")) return;
            try { await call("api/processes/" + p.pid + "/kill", "POST"); $("proc_msg").textContent = p.name + " beendet."; }
            catch (e) { $("proc_msg").textContent = e.message; }
            setTimeout(loadProcesses, 800);
          };
          r.append(kill);
        }
        box.append(r);
      }
      $("proc_vramhint").hidden = d.vram_available || psort !== "vram";
    } catch (e) { $("proc_msg").textContent = e.message; }
  }
  $("proc_sort").querySelectorAll(".segbtn").forEach(b => { b.onclick = () => { psort = b.dataset.k; store.set("pcc_psort", psort); loadProcesses(); }; });
  $("proc_box").addEventListener("toggle", loadProcesses);
  $("proc_reload").onclick = loadProcesses;

  /* ---------------- Zwischenablage ---------------- */
  $("clip_send").onclick = async () => {
    const text = $("clip_text").value;
    if (!text) return;
    $("clip_msg").textContent = "…";
    try { await call("api/action/clipboard_set", "POST", { text }); $("clip_msg").textContent = "An den PC gesendet ✓ (Strg+V)."; }
    catch (e) { $("clip_msg").textContent = e.message; }
  };
  $("clip_get").onclick = async () => {
    $("clip_msg").textContent = "…";
    try {
      const d = await call("api/clipboard");
      $("clip_text").value = d.text || "";
      $("clip_msg").textContent = d.text ? "Inhalt vom PC geholt." : "Die Zwischenablage des PCs enthält keinen Text.";
    } catch (e) { $("clip_msg").textContent = e.message; }
  };
  window.addEventListener("pcc:features", () => { $("clip_get").hidden = !features.includes("clipboard_read"); });

  /* ---------------- Screenshot ---------------- */
  $("shot_btn").onclick = async () => {
    $("extra_msg").textContent = "Mache Screenshot …";
    try {
      const r = await fetch(pcq("api/screenshot?width=1600"), { headers: authHeaders() });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ("Fehler " + r.status));
      openViewer({ blob: await r.blob(), title: "Screenshot", filename: "screenshot-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".jpg" });
      $("extra_msg").textContent = "";
    } catch (e) { $("extra_msg").textContent = e.message; }
  };

  /* ---------------- Jobs: Abbrechen und Verlauf ---------------- */
  $("jcancel").onclick = async () => {
    const s = states[current], j = s && s.snapshot && s.snapshot.job;
    if (!j || !confirm("Job „" + (j.title || j.tool) + "“ abbrechen?")) return;
    $("jcancel").disabled = true;
    try { await call("api/job/" + encodeURIComponent(j.job_id) + "/cancel", "POST"); }
    catch (e) { alert(e.message); }
    $("jcancel").disabled = false;
  };

  const ICON = { done: "✓", error: "✗" };
  async function loadHistory() {
    if (!features.includes("job_history")) return;
    try {
      const d = await call("api/jobs/history?limit=12");
      const box = $("hist_list");
      box.textContent = "";
      if (!d.jobs.length) { box.textContent = "Noch keine abgeschlossenen Jobs."; box.className = "muted"; return; }
      box.className = "";
      for (const j of d.jobs) {
        const r = row("devrow" + (j.state === "error" ? " bad" : ""));
        const info = document.createElement("div");
        const b = document.createElement("b");
        b.textContent = (ICON[j.state] || "") + " " + j.tool + (j.title ? ": " + j.title : "");
        const sm = document.createElement("small");
        sm.className = "muted";
        sm.textContent = new Date(j.finished * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
          + " · " + mm(j.duration_s) + (j.message ? " · " + j.message : "");
        info.append(b, document.createElement("br"), sm);
        r.append(info);
        box.append(r);
      }
    } catch (e) { /* Verlauf ist nur Zusatz */ }
  }

  whileVisible("ctrl", loadProcesses, 8000);
  whileVisible("tools", () => { loadHistory(); loadPrograms(); }, 10000);      // Programme (ComfyUI …) stehen bei den KI-Tools
  window.addEventListener("pcc:features", () => { loadPrograms(); });
})();
