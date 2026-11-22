"use strict";
// Aktionen aus Benachrichtigungen (Phase 10.3): Die Knöpfe der Home-Assistant-Meldungen öffnen die PWA mit  #do=<Befehl>&pc=<PC> .
// Sicherheit: nur feste Befehle, jede Aktion wird einmal bestätigt, Nur-Ansicht-Geräte dürfen nur Reiter öffnen, der Hub prüft die Rechte erneut.
(function () {
  const m = /^#do=([^&]+)(?:&pc=([^&]*))?/.exec(location.hash);
  if (!m) return;
  history.replaceState(null, "", location.pathname + location.search);          // der Befehl darf nicht bei jedem Neuladen wieder laufen
  let cmd = "", pcId = "";
  try { cmd = decodeURIComponent(m[1]); pcId = decodeURIComponent(m[2] || ""); } catch (e) { return; }
  const TABS = ["dash", "tools", "ctrl", "gallery", "steam", "claude", "files"];
  const ID = /^[A-Za-z0-9._:-]{1,80}$/;
  let done = false;

  function toast(text, ok) {
    const t = document.getElementById("launchtoast");
    if (!t) return;
    t.textContent = text; t.className = "toast" + (ok === false ? " bad" : ok ? " good" : ""); t.hidden = false;
    setTimeout(() => { t.hidden = true; }, 12000);
  }
  async function post(path, label) {
    try {
      const r = await fetch(pcq(path), { method: "POST", headers: authHeaders() });
      const d = await r.json().catch(() => ({}));
      toast(r.ok ? label + " ✓" : "Fehlgeschlagen: " + (d.detail || r.status), r.ok);
    } catch (e) { toast("Hub nicht erreichbar", false); }
  }

  async function execute(st) {
    const [name, arg] = [cmd.split(":")[0], cmd.includes(":") ? cmd.slice(cmd.indexOf(":") + 1) : ""];
    if (name === "tab") { if (TABS.includes(arg)) showTab(arg); return; }
    if (role !== "full") { toast("Dieses Gerät darf nur ansehen.", false); return; }
    if (name === "wake") {
      if (st.status === "online") { toast("Der PC ist schon online.", true); return; }
      if (confirm("PC jetzt aufwecken?")) await post("api/wake", "Aufwecken gesendet");
    } else if (name === "standby") {
      if (st.status !== "online") { toast("Der PC ist nicht online.", false); return; }
      if (confirm("PC jetzt in den Energiesparmodus schicken?")) await post("api/action/standby", "Energiesparmodus");
    } else if (name === "cancel-job" && ID.test(arg)) {
      if (st.status !== "online") { toast("Der PC ist nicht online.", false); return; }
      if (confirm("Den laufenden KI-Job abbrechen?")) await post("api/job/" + encodeURIComponent(arg) + "/cancel", "Abbruch angefordert");
    } else if (name === "scene" && ID.test(arg)) {
      if (confirm("Szene ausführen?")) await post("api/scenes/" + encodeURIComponent(arg) + "/run", "Szene gestartet");
    } else toast("Unbekannte Aktion.", false);
  }

  window.addEventListener("pcc:state", e => {
    if (done) return;
    const st = e.detail;
    if (pcId && st.pc !== pcId) {                                                // Meldung gehört zu einem anderen PC: dorthin wechseln
      if (typeof pcList !== "undefined" && pcList.some(p => p.id === pcId)) selectPc(pcId);
      else pcId = "";
      return;
    }
    done = true;
    execute(st);
  });
})();
