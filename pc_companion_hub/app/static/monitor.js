"use strict";
// Gesundheit & Statistik (Phase 10.7): Karte auf dem Dashboard. Die Auswertung macht der Hub bzw. der Agent; hier wird nur angezeigt.
(function () {
  const $ = id => document.getElementById(id);
  let loadedPc = null, timer = 0;
  const h = (n, f) => n >= 60 ? (n / 60).toFixed(1).replace(".", ",") + " Std." : Math.round(n) + " Min.";
  const mk = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
  function row(left, right) { const d = mk("div", null, "mh"); d.append(mk("span", left), mk("b", right)); return d; }

  async function get(path) {
    const r = await fetch(pcq(path), { headers: authHeaders() });
    return r.ok ? r.json() : null;
  }
  async function load() {
    const [hc, st] = await Promise.all([get("api/health-check").catch(() => null), get("api/stats").catch(() => null)]);
    const box = $("mon_issues");
    if (hc) {
      box.textContent = "";
      if (hc.supported === false) box.append(mk("div", "Der Agent kann (noch) keine Gesundheitsprüfung – bitte aktualisieren.", "muted"));
      else if (hc.checked == null) box.append(mk("div", "Erste Prüfung läuft …", "muted"));
      else if (!hc.issues.length) box.append(mk("div", "Alles in Ordnung.", "muted"));
      for (const i of hc.issues || []) box.append(mk("div", (i.level === "bad" ? "⛔ " : "⚠️ ") + i.text, i.level === "bad" ? "bad" : ""));
      const sm = $("mon_disks");
      sm.textContent = "";
      for (const d of hc.disks || []) sm.append(row(d.mount + " (" + Math.round(d.total_gb) + " GB)", Math.round(d.free_gb) + " GB frei"));
      for (const s of hc.smart || []) sm.append(row(s.name, s.health || "–"));
      if (hc.gpu_driver) sm.append(row("GPU-Treiber", hc.gpu_driver));
      if (hc.uptime_days != null) sm.append(row("Laufzeit seit Start", Math.floor(hc.uptime_days) + " Tage"));
    }
    if (st) {
      const g = $("mon_games"); g.textContent = "";
      const max = Math.max(1, ...st.games_weekly.map(w => w.minutes));
      const bars = mk("div", null, "enbars");
      for (const w of st.games_weekly) {
        const i = document.createElement("i");
        i.style.height = Math.max(3, Math.round(100 * w.minutes / max)) + "%";
        i.title = "Woche ab " + w.week.slice(8) + "." + w.week.slice(5, 7) + ".: " + h(w.minutes) + (w.top ? " · meist " + w.top : "");
        bars.append(i);
      }
      g.append(bars);
      const last = st.games_weekly[st.games_weekly.length - 1];
      g.append(mk("div", "Diese Woche: " + h(last.minutes) + (last.top ? " – am meisten " + last.top + " (" + h(last.top_minutes) + ")" : ""), "muted"));
      const j = $("mon_jobs"); j.textContent = "";
      for (const t of st.jobs.trend) j.append(row(t.tool, h(t.recent_min) + " (zuvor " + h(t.before_min) + (t.change_pct != null ? ", " + (t.change_pct > 0 ? "+" : "") + t.change_pct + " %" : "") + ")"));
      for (const x of st.jobs.jobs.slice(0, 6)) j.append(row(x.name, h(x.minutes)));
      if (!st.jobs.jobs.length) j.append(mk("div", "Noch keine KI-Jobs erfasst.", "muted"));
      const u = $("mon_usage"); u.textContent = "";
      const bars2 = mk("div", null, "enbars");
      for (const d of st.usage) {
        const i = document.createElement("i");
        i.style.height = Math.max(3, Math.round(d.gpu_avg || 0)) + "%";
        i.title = d.day.slice(8) + "." + d.day.slice(5, 7) + ".: " + (d.gpu_avg == null ? "keine Daten" : "GPU im Mittel " + d.gpu_avg + " %, ausgelastet " + h(d.busy_min));
        bars2.append(i);
      }
      u.append(bars2);
    }
  }
  function watch() {
    clearInterval(timer); timer = 0;
    if (!$("monbox").closest(".view").hidden) { load(); timer = setInterval(() => { if (!document.hidden) load(); }, 120000); }
  }
  new MutationObserver(watch).observe($("monbox").closest(".view"), { attributes: true, attributeFilter: ["hidden"] });
  window.addEventListener("pcc:state", () => { if (loadedPc !== current) { loadedPc = current; watch(); } });
  window.addEventListener("pcc:pc", () => { loadedPc = null; });
})();
