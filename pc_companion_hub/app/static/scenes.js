"use strict";
// Szenen (Phase 10.2): Schnellstart auf dem Dashboard, Verwaltung und Editor unter Steuerung → Szenen, Fortschrittskarte.
// Gespeichert und ausgeführt wird im Hub; hier nur Anzeige und Bedienung.
(function () {
  const $ = id => document.getElementById(id);
  const ACTIONS = {
    lock: "Sperren", sleep: "Ruhezustand", standby: "Energiesparmodus", shutdown: "Herunterfahren", restart: "Neustart", monitor_off: "Bildschirm aus",
    mute: "Stumm schalten", volume: "Lautstärke setzen", media_play_pause: "Wiedergabe/Pause", media_next: "Nächster Titel", media_prev: "Vorheriger Titel",
  };
  const POWER = { standby: "Energiesparmodus", sleep: "Ruhezustand", shutdown: "Herunterfahren" };
  const TYPES = [
    ["program_stop", "Programm beenden"], ["program_start", "Programm starten"], ["game_launch", "Spiel starten"], ["game_stop", "Spiel beenden"],
    ["action", "PC-Aktion"], ["power_plan", "Energie-Plan"], ["ha_scene", "Home-Assistant-Szene"], ["wait", "Warten"], ["notify", "Nachricht senden"],
  ];
  let scenes = [], limits = { max_steps: 30, max_wait_s: 300, actions: Object.keys(ACTIONS) }, editing = null, steps = [], lists = { programs: null, games: null };

  async function call(method, path, body) {
    const r = await fetch(pcq(path), { method, headers: { ...authHeaders(), ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
    return d;
  }

  /* ---- Liste, Schnellstart ---- */
  async function load() {
    try { const d = await call("GET", "api/scenes"); scenes = d.scenes || []; limits = d.limits || limits; } catch (e) { scenes = []; }
    paint();
  }
  function chipLabel(s) { return (s.icon ? s.icon + " " : "") + s.name; }
  function paint() {
    const chips = $("scene_chips"), list = $("scene_list");
    chips.textContent = ""; list.textContent = "";
    $("scenebox").hidden = !scenes.length;
    $("scene_empty").hidden = scenes.length > 0;
    for (const s of scenes) {
      const b = document.createElement("button");
      b.className = "chip stctl"; b.textContent = chipLabel(s); b.title = s.steps.length + " Schritte";
      b.onclick = () => run(s);
      chips.append(b);
      const row = document.createElement("div");
      row.className = "devrow";
      const info = document.createElement("div"), nm = document.createElement("b"), sm = document.createElement("small");
      nm.textContent = chipLabel(s); sm.className = "muted"; sm.textContent = " " + s.steps.length + (s.steps.length === 1 ? " Schritt" : " Schritte");
      info.append(nm, sm);
      const acts = document.createElement("div");
      acts.className = "row";
      for (const [label, fn] of [["▶", () => run(s)], ["Bearbeiten", () => openEditor(s)], ["Löschen", () => remove(s)]]) {
        const b2 = document.createElement("button");
        b2.textContent = label; b2.onclick = fn; if (label === "▶") b2.className = "primary";
        acts.append(b2);
      }
      row.append(info, acts);
      list.append(row);
    }
  }
  async function run(s) {
    if (!confirm("Szene „" + s.name + "“ ausführen? (" + s.steps.length + " Schritte)")) return;
    try { await call("POST", "api/scenes/" + encodeURIComponent(s.id) + "/run"); showCard(); } catch (e) { alert(e.message); }
  }
  async function remove(s) {
    if (!confirm("Szene „" + s.name + "“ löschen?")) return;
    try { await call("DELETE", "api/scenes/" + encodeURIComponent(s.id)); await load(); } catch (e) { alert(e.message); }
  }

  /* ---- Fortschrittskarte (kommt über die normale Statusmeldung) ---- */
  const MARK = { pending: "○", running: "…", ok: "✓", error: "✗", skipped: "–" };
  let cardHidden = 0;
  function showCard() { cardHidden = 0; }
  window.addEventListener("pcc:state", e => {
    const r = e.detail.scene_run, card = $("scene_run");
    if (!r || (cardHidden && cardHidden === r.started)) { card.hidden = true; return; }
    card.hidden = false;
    card.className = "scenecard " + r.state;
    $("scene_run_title").textContent = r.name + " – " + ({ running: "läuft", ok: "fertig", error: "fehlgeschlagen", cancelled: "abgebrochen" })[r.state];
    const box = $("scene_run_steps");
    box.textContent = "";
    r.steps.forEach((s, i) => {
      const d = document.createElement("div");
      d.className = "scstep " + s.state;
      d.textContent = (MARK[s.state] || "○") + " " + s.label;
      if (s.error) { const x = document.createElement("small"); x.textContent = " – " + s.error; d.append(x); }
      box.append(d);
    });
    $("scene_run_cancel").hidden = r.state !== "running";
    $("scene_run_close").hidden = r.state === "running";
    $("scene_run_err").textContent = r.state === "error" ? r.error : "";
    $("scene_run_cancel").onclick = async () => { try { await call("POST", "api/scenes/cancel"); } catch (er) { alert(er.message); } };
    $("scene_run_close").onclick = () => { cardHidden = r.started; card.hidden = true; };
  });

  /* ---- Editor ---- */
  async function ensureLists() {
    if (!lists.programs) { try { lists.programs = (await call("GET", "api/programs")).programs || []; } catch (e) { lists.programs = []; } }
    if (!lists.games) { try { lists.games = (await call("GET", "api/steam/games?sort=name")).games || []; } catch (e) { lists.games = []; } }
  }
  function field(el, label) {
    const w = document.createElement("label");
    w.className = "scf";
    const sp = document.createElement("span"); sp.textContent = label;
    w.append(sp, el); return w;
  }
  function select(options, value, onchange) {
    const s = document.createElement("select");
    for (const [v, l] of options) s.append(new Option(l, v));
    s.value = value; s.onchange = () => onchange(s.value); return s;
  }
  function input(type, value, onchange, attrs) {
    const i = document.createElement("input");
    i.type = type; i.value = value == null ? "" : value; Object.assign(i, attrs || {});
    i.oninput = () => onchange(type === "number" ? (i.value === "" ? null : Number(i.value)) : i.value); return i;
  }
  function stepFields(st, i) {
    const out = [];
    const t = st.type;
    if (t === "program_start" || t === "program_stop") {
      const opts = (lists.programs || []).map(p => [p.id, p.name]);
      if (st.id && !opts.some(o => o[0] === st.id)) opts.unshift([st.id, st.name || st.id]);
      if (opts.length) out.push(field(select(opts, st.id || opts[0][0], v => { st.id = v; st.name = (opts.find(o => o[0] === v) || [])[1] || ""; }), "Programm"));
      else out.push(field(input("text", st.id || "", v => { st.id = v; st.name = v; }, { placeholder: "Programm-ID" }), "Programm-ID"));
      if (!st.id && opts.length) { st.id = opts[0][0]; st.name = opts[0][1]; }
    } else if (t === "game_launch" || t === "game_stop") {
      const opts = (lists.games || []).map(g => [String(g.appid), g.name]);
      if (st.appid && !opts.some(o => o[0] === String(st.appid))) opts.unshift([String(st.appid), st.name || String(st.appid)]);
      if (opts.length) {
        out.push(field(select(opts, String(st.appid || opts[0][0]), v => { st.appid = Number(v); st.name = (opts.find(o => o[0] === v) || [])[1] || ""; }), "Spiel"));
        if (!st.appid) { st.appid = Number(opts[0][0]); st.name = opts[0][1]; }
      } else out.push(field(input("number", st.appid, v => { st.appid = v; }, { placeholder: "AppID" }), "AppID"));
      if (t === "game_launch") {
        const c = document.createElement("input"); c.type = "checkbox"; c.checked = !!st.force; c.onchange = () => { st.force = c.checked; };
        const w = document.createElement("label"); w.className = "chk"; w.append(c, document.createTextNode(" auch starten, wenn ein anderes Spiel läuft")); out.push(w);
      }
    } else if (t === "action") {
      out.push(field(select((limits.actions || Object.keys(ACTIONS)).map(a => [a, ACTIONS[a] || a]), st.name || "lock", v => { st.name = v; if (v === "volume" && st.level == null) st.level = 30; if (v !== "volume") delete st.level; render(); }), "Aktion"));
      if (!st.name) st.name = "lock";
      if (st.name === "volume") out.push(field(input("number", st.level == null ? 30 : st.level, v => { st.level = v; }, { min: 0, max: 100 }), "Lautstärke (0–100)"));
    } else if (t === "power_plan") {
      const cur = st.cancel ? "cancel" : (st.after_job || "standby");
      out.push(field(select([...Object.entries(POWER).map(([k, l]) => [k, "Nach dem letzten Job: " + l]), ["cancel", "Energie-Plan aufheben"]], cur, v => {
        delete st.after_job; delete st.cancel; delete st.timer_minutes; delete st.mode; if (v === "cancel") st.cancel = true; else st.after_job = v;
      }), "Energie-Plan"));
      if (!st.cancel && !st.after_job) st.after_job = "standby";
    } else if (t === "ha_scene") {
      out.push(field(input("text", st.entity_id || "", v => { st.entity_id = v.trim(); }, { placeholder: "scene.zocken" }), "Home-Assistant-Szene"));
    } else if (t === "wait") {
      out.push(field(input("number", st.seconds == null ? 5 : st.seconds, v => { st.seconds = v; }, { min: 1, max: limits.max_wait_s }), "Sekunden (1–" + limits.max_wait_s + ")"));
      if (st.seconds == null) st.seconds = 5;
    } else if (t === "notify") {
      out.push(field(input("text", st.message || "", v => { st.message = v; }, { placeholder: "Text der Nachricht", maxLength: 200 }), "Nachricht"));
    }
    return out;
  }
  function render() {
    const box = $("sc_steps");
    box.textContent = "";
    steps.forEach((st, i) => {
      const row = document.createElement("div");
      row.className = "scrow";
      const head = document.createElement("div"), ttl = document.createElement("b");
      head.className = "schead";
      ttl.textContent = (i + 1) + ". " + (TYPES.find(t => t[0] === st.type) || [, st.type])[1];
      const ctl = document.createElement("span");
      for (const [label, fn, off] of [["↑", () => { [steps[i - 1], steps[i]] = [steps[i], steps[i - 1]]; render(); }, i === 0], ["↓", () => { [steps[i + 1], steps[i]] = [steps[i], steps[i + 1]]; render(); }, i === steps.length - 1], ["✕", () => { steps.splice(i, 1); render(); }, false]]) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "scbtn"; b.textContent = label; b.disabled = off; b.onclick = fn; ctl.append(b);
      }
      head.append(ttl, ctl);
      row.append(head, ...stepFields(st, i));
      box.append(row);
    });
    $("sc_empty_steps").hidden = steps.length > 0;
  }
  async function openEditor(s) {
    await ensureLists();
    editing = s ? s.id : null;
    $("sc_title").textContent = s ? "Szene bearbeiten" : "Neue Szene";
    $("sc_name").value = s ? s.name : "";
    $("sc_icon").value = s ? s.icon : "";
    $("sc_wake").checked = s ? s.wake !== false : true;
    steps = s ? JSON.parse(JSON.stringify(s.steps)) : [];
    $("sc_msg").textContent = "";
    render();
    $("sc_sheet").hidden = false;
  }
  function closeEditor() { $("sc_sheet").hidden = true; editing = null; }
  $("sc_add_btn").onclick = () => {
    const t = $("sc_add").value;
    if (steps.length >= limits.max_steps) { $("sc_msg").textContent = "Höchstens " + limits.max_steps + " Schritte"; return; }
    steps.push({ type: t }); render();
  };
  $("sc_save").onclick = async () => {
    const body = { name: $("sc_name").value, icon: $("sc_icon").value, wake: $("sc_wake").checked, steps };
    $("sc_msg").textContent = "Speichere …";
    try {
      await call(editing ? "PUT" : "POST", "api/scenes" + (editing ? "/" + encodeURIComponent(editing) : ""), body);
      closeEditor(); await load();
    } catch (e) { $("sc_msg").textContent = e.message; }
  };
  $("sc_cancel").onclick = closeEditor;
  $("sc_sheet").addEventListener("click", e => { if (e.target === $("sc_sheet")) closeEditor(); });
  $("scene_new").onclick = () => openEditor(null);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("sc_sheet").hidden) closeEditor(); });
  for (const [k, l] of TYPES) $("sc_add").append(new Option(l, k));

  let loadedPc = null;
  window.addEventListener("pcc:state", () => { if (loadedPc !== current) { loadedPc = current; lists = { programs: null, games: null }; load(); } });
})();
