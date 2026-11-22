"use strict";
// Claude-Code-Übersicht: welche Sitzungen am PC laufen, was sie gerade tun, ihre Aufgabenliste und Unter-Agenten. Nur Anzeige.
(function () {
  const $ = id => document.getElementById(id);
  let timer = 0, busy = false;
  const mk = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  const ago = s => s < 5 ? "gerade eben" : s < 60 ? "vor " + s + " Sek." : s < 3600 ? "vor " + Math.round(s / 60) + " Min." : s < 86400 ? "vor " + Math.round(s / 3600) + " Std." : "vor " + Math.round(s / 86400) + " Tg.";
  const STATE = { busy: "arbeitet", idle: "wartet", shell: "Befehl läuft", ended: "beendet" };
  const MARK = { completed: "✓", in_progress: "▶", pending: "○" };

  function toolLine(t) {
    if (!t) return null;
    const d = mk("div", null, "cctool");
    d.append(mk("b", t.name.replace(/^mcp__/, "").replace(/__/g, " › ")), mk("span", t.summary ? " – " + t.summary : ""));
    if (t.running) d.append(mk("span", " läuft", "ccrun"));
    return d;
  }

  function card(s) {
    const c = mk("div", null, "cccard " + (s.status || ""));
    const head = mk("div", null, "cchead");
    head.append(mk("span", "", "ccdot"), mk("b", s.name), mk("span", STATE[s.status] || s.status, "ccstate"));
    c.append(head);
    c.append(mk("div", [s.project, s.branch, s.entrypoint === "cli" ? "Terminal" : s.entrypoint === "claude-desktop" ? "Desktop-App" : s.entrypoint, ago(s.updated_s)].filter(Boolean).join(" · "), "muted ccmeta"));
    const t = toolLine(s.tool);
    if (t && s.alive) c.append(t);
    if (s.text && s.alive) c.append(mk("div", "„" + s.text + "“", "cctext"));
    if (s.plan && s.plan.length) {
      const done = s.plan.filter(p => p.status === "completed").length;
      const pl = mk("div", null, "ccplan");
      pl.append(mk("div", "Aufgaben " + done + " / " + s.plan.length, "muted"));
      for (const p of s.plan) pl.append(mk("div", (MARK[p.status] || "○") + " " + p.content, "ccp " + p.status));
      c.append(pl);
    }
    const run = (s.subagents || []).filter(a => !a.finished), fin = (s.subagents || []).filter(a => a.finished);
    if (run.length || fin.length) {
      const sb = mk("div", null, "ccsubs");
      sb.append(mk("div", "Unter-Agenten: " + run.length + " laufen" + (fin.length ? ", " + fin.length + " fertig" : ""), "muted"));
      for (const a of run) {
        const r = mk("div", null, "ccsub run");
        r.append(mk("b", a.type), mk("span", " – " + a.description));
        if (a.tool) r.append(mk("div", a.tool.name + (a.tool.summary ? ": " + a.tool.summary : ""), "muted cctool2"));
        sb.append(r);
      }
      for (const a of fin.slice(0, 4)) sb.append(mk("div", "✓ " + a.type + " – " + a.description + " (" + ago(a.age_s) + ")", "ccsub fin muted"));
      c.append(sb);
    }
    return c;
  }

  async function load() {
    if (busy || !features.includes("claude_code")) return;
    busy = true;
    try {
      const r = await fetch(pcq("api/claude"), { headers: authHeaders() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
      $("cc_msg").textContent = "";
      $("cc_sum").textContent = d.sessions.length ? d.busy + " arbeiten · " + d.subagents_running + " Unter-Agenten laufen · " + d.sessions.length + " Sitzungen" : "";
      const box = $("cc_list");
      box.textContent = "";
      for (const s of d.sessions) box.append(card(s));
      if (!d.sessions.length) box.append(mk("div", "Keine Claude-Code-Sitzungen gefunden.", "muted"));
    } catch (e) { $("cc_msg").textContent = e.message; }
    busy = false;
  }

  const view = document.querySelector('[data-view="claude"]');
  function sync() {
    clearInterval(timer); timer = 0;
    if (!view.hidden) { load(); timer = setInterval(() => { if (!document.hidden) load(); }, 5000); }
  }
  new MutationObserver(sync).observe(view, { attributes: true, attributeFilter: ["hidden"] });
  $("cc_reload").onclick = load;
  window.addEventListener("pcc:pc", () => { $("cc_list").textContent = ""; $("cc_sum").textContent = ""; });
  window.addEventListener("pcc:features", () => { if (!view.hidden) load(); });
})();
