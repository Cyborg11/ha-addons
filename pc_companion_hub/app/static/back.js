"use strict";
// Zurück-Taste (Android/Browser) arbeitet innerhalb der App: erst offene Fenster/Bildbetrachter schließen, dann zum vorigen Reiter,
// erst vom Dashboard aus verlässt sie die App. Nutzt die Verlaufs-API (history.pushState), keine Adressänderung.
(function () {
  const overlays = [...document.querySelectorAll(".sheet, #viewer")];
  const has = new Map(overlays.map(o => [o, false]));      // Fenster -> hat einen Verlaufseintrag
  const stack = [];                                       // offene Fenster in Öffnungsreihenfolge
  let ignorePop = false, userNav = false, cur = null, initDone = false;
  const base = history.state || {};
  try { history.replaceState({ ...base, pcc: "tab", tab: base.tab || "dash" }, ""); } catch (e) { return; }

  // ---- Reiter
  const origShowTab = window.showTab;
  if (typeof origShowTab === "function") {
    window.showTab = function (name) {
      origShowTab(name);
      const now = tab;
      if (!initDone && !userNav) {                         // wiederhergestellter Reiter beim Start: Dashboard darunter legen, damit Zurück dorthin führt
        initDone = true;
        if (now !== "dash") { history.replaceState({ pcc: "tab", tab: "dash" }, ""); history.pushState({ pcc: "tab", tab: now }, ""); }
      } else if (userNav && now !== cur) { initDone = true; history.pushState({ pcc: "tab", tab: now }, ""); }
      cur = now; userNav = false;
    };
    document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => { userNav = true; }, true));
  }

  // ---- Fenster (Bildbetrachter, Dialoge)
  function closeOverlay(el) {
    if (el.id === "pin_sheet") { const c = document.getElementById("pin_cancel"); if (c) c.click(); }
    else el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }
  new MutationObserver(() => {
    for (const o of overlays) {
      const open = !o.hidden;
      if (open && !has.get(o)) { has.set(o, true); stack.push(o); history.pushState({ pcc: "layer" }, ""); }
      else if (!open && has.get(o)) {                      // per Knopf geschlossen: den Verlaufseintrag wieder entfernen
        has.set(o, false);
        const i = stack.indexOf(o); if (i >= 0) stack.splice(i, 1);
        ignorePop = true; history.back();
      }
    }
  }).observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });

  window.addEventListener("popstate", e => {
    if (ignorePop) { ignorePop = false; return; }
    const top = stack[stack.length - 1];
    if (top) {                                             // Zurück schließt das oberste Fenster
      stack.pop(); has.set(top, false);
      closeOverlay(top);
      if (!top.hidden) { has.set(top, true); stack.push(top); history.pushState({ pcc: "layer" }, ""); }   // ließ sich nicht schließen (z. B. läuft gerade etwas)
      return;
    }
    const st = e.state || {};
    if (st.pcc === "tab" || !st.pcc) { cur = st.tab || "dash"; userNav = false; origShowTab(cur); }
  });
})();
