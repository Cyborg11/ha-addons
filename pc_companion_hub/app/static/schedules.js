"use strict";
// Zeitpläne (Phase 10.5): Liste und Editor unter Steuerung → Automatik. Die Ausführung macht der Hub (auch bei ausgeschaltetem PC).
(function () {
  const $ = id => document.getElementById(id);
  const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
  const MODES = { standby: "Energiesparmodus", sleep: "Ruhezustand", shutdown: "Herunterfahren" };
  let items = [], editing = null, days = new Set(), sceneList = [];

  async function call(method, path, body) {
    const r = await fetch(pcq(path), { method, headers: { ...authHeaders(), ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }
  const fmtDate = iso => { const d = new Date(iso + "T12:00:00"); return DAYS[(d.getDay() + 6) % 7] + " " + d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }); };

  async function load() {
    try { const d = await call("GET", "api/schedules"); items = d.schedules || []; $("sched_tz").textContent = d.timezone ? "Zeitzone: " + d.timezone : ""; } catch (e) { items = []; }
    paint();
  }
  function paint() {
    const list = $("sched_list");
    list.textContent = "";
    $("sched_empty").hidden = items.length > 0;
    for (const s of items) {
      const row = document.createElement("div");
      row.className = "devrow schedrow" + (s.enabled ? "" : " off");
      const info = document.createElement("div"), nm = document.createElement("b"), tx = document.createElement("div"), nx = document.createElement("small");
      nm.textContent = s.name; tx.textContent = s.text; tx.className = "muted";
      nx.className = "muted";
      nx.textContent = !s.enabled ? "ausgeschaltet" : (s.skip_date && s.skip_date === s.next ? "nächster Lauf übersprungen (" + fmtDate(s.skip_date) + ")" : "nächster Lauf: " + fmtDate(s.next));
      info.append(nm, tx, nx);
      const acts = document.createElement("div");
      acts.className = "row";
      const btns = [
        [s.skip_date ? "Nicht überspringen" : "Nächsten überspringen", async () => { try { await call(s.skip_date ? "DELETE" : "POST", "api/schedules/" + encodeURIComponent(s.id) + "/skip"); await load(); } catch (e) { alert(e.message); } }],
        [s.enabled ? "Aus" : "An", async () => { try { await call("PUT", "api/schedules/" + encodeURIComponent(s.id), { ...strip(s), enabled: !s.enabled }); await load(); } catch (e) { alert(e.message); } }],
        ["Bearbeiten", () => openEditor(s)],
        ["Löschen", async () => { if (!confirm("Zeitplan „" + s.name + "“ löschen?")) return; try { await call("DELETE", "api/schedules/" + encodeURIComponent(s.id)); await load(); } catch (e) { alert(e.message); } }],
      ];
      for (const [label, fn] of btns) { const b = document.createElement("button"); b.className = "stctl"; b.type = "button"; b.textContent = label; b.onclick = fn; acts.append(b); }
      row.append(info, acts);
      list.append(row);
    }
  }
  const strip = s => ({ name: s.name, days: s.days, time: s.time, action: s.action, enabled: s.enabled, ...(s.pc ? { pc: s.pc } : {}) });

  /* ---- Editor ---- */
  function paintDays() {
    const box = $("sched_days");
    box.textContent = "";
    DAYS.forEach((d, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "segbtn" + (days.has(i) ? " on" : ""); b.textContent = d;
      b.onclick = () => { days.has(i) ? days.delete(i) : days.add(i); paintDays(); };
      box.append(b);
    });
  }
  function paintAction() {
    const t = $("sched_type").value;
    $("sched_scene_box").hidden = t !== "scene";
    $("sched_idle_box").hidden = t !== "standby_if_idle";
  }
  async function openEditor(s) {
    try { sceneList = (await call("GET", "api/scenes")).scenes || []; } catch (e) { sceneList = []; }
    editing = s ? s.id : null;
    $("sched_title").textContent = s ? "Zeitplan bearbeiten" : "Neuer Zeitplan";
    $("sched_name").value = s ? s.name : "";
    $("sched_time").value = s ? s.time : "07:30";
    days = new Set(s ? s.days : [0, 1, 2, 3, 4]);
    $("sched_enabled").checked = s ? s.enabled : true;
    const a = s ? s.action : { type: "wake" };
    $("sched_type").value = a.type;
    const sel = $("sched_scene");
    sel.textContent = "";
    for (const sc of sceneList) sel.append(new Option(sc.name, sc.id));
    if (a.scene_id) sel.value = a.scene_id;
    $("sched_idle_min").value = a.idle_minutes || 10;
    $("sched_window_min").value = a.window_minutes || 120;
    $("sched_mode").value = a.mode || "standby";
    $("sched_msg").textContent = sceneList.length ? "" : (a.type === "scene" ? "Es gibt noch keine Szene." : "");
    paintDays(); paintAction();
    $("sched_sheet").hidden = false;
  }
  function closeEditor() { $("sched_sheet").hidden = true; editing = null; }
  $("sched_type").onchange = paintAction;
  $("sched_cancel").onclick = closeEditor;
  $("sched_sheet").addEventListener("click", e => { if (e.target === $("sched_sheet")) closeEditor(); });
  $("sched_new").onclick = () => openEditor(null);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("sched_sheet").hidden) closeEditor(); });
  for (const [k, l] of Object.entries(MODES)) $("sched_mode").append(new Option(l, k));
  $("sched_save").onclick = async () => {
    const t = $("sched_type").value;
    const action = t === "scene" ? { type: t, scene_id: $("sched_scene").value }
      : t === "standby_if_idle" ? { type: t, idle_minutes: Number($("sched_idle_min").value), window_minutes: Number($("sched_window_min").value), mode: $("sched_mode").value } : { type: t };
    const body = { name: $("sched_name").value, days: [...days].sort(), time: $("sched_time").value, action, enabled: $("sched_enabled").checked };
    $("sched_msg").textContent = "Speichere …";
    try { await call(editing ? "PUT" : "POST", "api/schedules" + (editing ? "/" + encodeURIComponent(editing) : ""), body); closeEditor(); await load(); }
    catch (e) { $("sched_msg").textContent = e.message; }
  };

  let loadedPc = null;
  window.addEventListener("pcc:state", () => { if (loadedPc !== current) { loadedPc = current; load(); } });
  setInterval(() => { if (!document.hidden && !$("sched_list").closest(".subview").hidden) load(); }, 60000);   // „nächster Lauf“ aktuell halten
})();
