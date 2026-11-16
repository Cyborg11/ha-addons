"use strict";
// Sicherheits-PIN (Phase 10.4): Ist im Add-on `confirm_pin` gesetzt, antwortet der Hub bei kritischen Aktionen (Herunterfahren, Neustart, Ruhezustand,
// Energiesparmodus, Prozess/Programm/Spiel beenden, Szenen mit solchen Schritten) mit „428 PIN erforderlich“. Diese Datei fragt dann die PIN ab und
// wiederholt die Anfrage mit dem Header X-Confirm-PIN. Die Prüfung macht der Hub; hier ist nur die Eingabe. Die PIN wird nie gespeichert,
// nur 60 Sekunden im Speicher gehalten (damit eine Kette wie „Prozess beenden“ mehrfach nicht jedes Mal fragt).
(function () {
  const orig = window.fetch.bind(window);
  const KEEP_MS = 60000;
  let cached = null, cachedAt = 0, asking = null;

  function withPin(init, pin) {
    const headers = new Headers((init && init.headers) || {});
    headers.set("X-Confirm-PIN", pin);
    return { ...(init || {}), headers };
  }

  function ask(message) {
    if (asking) return asking;                                           // parallele Anfragen teilen sich einen Dialog
    asking = new Promise(resolve => {
      const sheet = document.getElementById("pin_sheet"), input = document.getElementById("pin_input");
      document.getElementById("pin_msg").textContent = message || "Diese Aktion ist mit einer PIN geschützt.";
      input.value = "";
      sheet.hidden = false;
      setTimeout(() => input.focus(), 50);
      const done = v => { sheet.hidden = true; document.getElementById("pin_ok").onclick = document.getElementById("pin_cancel").onclick = null; asking = null; resolve(v); };
      document.getElementById("pin_ok").onclick = () => done(input.value || null);
      document.getElementById("pin_cancel").onclick = () => done(null);
      input.onkeydown = e => { if (e.key === "Enter") done(input.value || null); else if (e.key === "Escape") done(null); };
    });
    return asking;
  }

  window.fetch = async function (input, init) {
    if (cached && Date.now() - cachedAt < KEEP_MS) {                       // frisch eingegebene PIN gleich mitschicken (nur an eigene API-Pfade, nie nach außen)
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (!/^https?:/i.test(url) || url.startsWith(location.origin)) {
        const r = await orig(input, withPin(init, cached));
        if (r.status !== 428 && r.status !== 403) return r;
        if (r.status === 403) cached = null;                              // falsche PIN
      }
    }
    const r = await orig(input, init);
    if (r.status !== 428) return r;
    let message = "";
    for (let tries = 0; tries < 3; tries++) {
      const pin = await ask(message);
      if (pin == null) return r;                                          // abgebrochen: der Aufrufer zeigt „PIN erforderlich“
      const r2 = await orig(input, withPin(init, pin));
      if (r2.status === 403) { message = "PIN falsch. Bitte noch einmal."; continue; }
      if (r2.status !== 428 && r2.status !== 429) { cached = pin; cachedAt = Date.now(); }       // PIN angenommen (egal, was die Aktion danach antwortet)
      return r2;                                                          // auch 429 (gesperrt): der Aufrufer zeigt den Grund
    }
    return orig(input, init);
  };
})();
