"use strict";
// Strom und Kosten (Phase 10.6): Karte auf dem Dashboard. Die Werte rechnet der Hub (nur gemessene GPU-/CPU-Leistung = Untergrenze).
(function () {
  const $ = id => document.getElementById(id);
  let loadedPc = null, timer = 0;
  const kwh = v => v == null ? "–" : v < 0.1 ? Math.round(v * 1000) + " Wh" : (v >= 10 ? v.toFixed(1) : v.toFixed(2)).replace(".", ",") + " kWh";
  const eur = v => v == null ? "" : v.toFixed(2).replace(".", ",") + " €";
  const dayLabel = iso => { const d = new Date(iso + "T12:00:00"); return ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"][d.getDay()]; };

  function row(left, right, sub) {
    const d = document.createElement("div"), a = document.createElement("span"), b = document.createElement("b");
    d.className = "mh"; a.textContent = left; b.textContent = right;
    d.append(a, b);
    if (sub) { const w = document.createElement("div"); w.className = "enrow"; const s = document.createElement("small"); s.className = "muted"; s.textContent = sub; w.append(d, s); return w; }
    return d;
  }
  function figure(label, v) {
    const d = document.createElement("div"), s = document.createElement("span"), b = document.createElement("b"), c = document.createElement("small");
    s.textContent = label; b.textContent = kwh(v.kwh); c.textContent = eur(v.eur);
    d.append(s, b, c); return d;
  }

  async function load() {
    try {
      const r = await fetch(pcq("api/energy?days=14"), { headers: authHeaders() });
      if (!r.ok) return;
      const d = await r.json();
      const box = $("en_figs");
      box.textContent = "";
      box.append(figure("Heute", d.today), figure("7 Tage", d.week), figure("Monat", d.month));
      const bars = $("en_bars");
      bars.textContent = "";
      const max = Math.max(0.001, ...d.days.map(x => x.kwh));
      for (const x of d.days) {
        const i = document.createElement("i");
        i.style.height = Math.max(3, Math.round(100 * x.kwh / max)) + "%";
        i.title = dayLabel(x.day) + " " + x.day.slice(8) + "." + x.day.slice(5, 7) + ".: " + kwh(x.kwh) + (x.eur != null ? " · " + eur(x.eur) : "");
        if (x.day === d.today.day) i.className = "now";
        bars.append(i);
      }
      const list = (box2, items, none) => {
        box2.textContent = "";
        if (!items.length) { const p = document.createElement("div"); p.className = "muted"; p.textContent = none; box2.append(p); return; }
        for (const it of items) {
          const when = new Date(it.start * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
          box2.append(row(it.name, kwh(it.kwh) + (it.eur != null ? " · " + eur(it.eur) : ""), when + " · " + it.minutes + " Min." + (it.tool ? " · " + it.tool : "")));
        }
      };
      list($("en_jobs"), d.jobs, "Noch kein abgeschlossener KI-Job erfasst.");
      list($("en_games"), d.games, "Noch keine Spielsitzung erfasst.");
      $("en_note").textContent = "Gemessen: " + d.coverage + ". Mainboard, Lüfter, Netzteil-Verluste und Peripherie fehlen – die Zahlen sind eine Untergrenze." +
        (d.price_ct_kwh == null ? " Für Kosten den Strompreis in den Add-on-Optionen setzen (strompreis_ct_kwh)." : " Preis: " + String(d.price_ct_kwh).replace(".", ",") + " ct/kWh.");
    } catch (e) { /* die Karte bleibt, wie sie ist */ }
  }
  function watch() {
    clearInterval(timer); timer = 0;
    if (!$("energybox").closest(".view").hidden) { load(); timer = setInterval(() => { if (!document.hidden) load(); }, 60000); }
  }
  new MutationObserver(watch).observe($("energybox").closest(".view"), { attributes: true, attributeFilter: ["hidden"] });
  window.addEventListener("pcc:state", () => { if (loadedPc !== current) { loadedPc = current; watch(); } });
  window.addEventListener("pcc:pc", () => { loadedPc = null; });
})();
