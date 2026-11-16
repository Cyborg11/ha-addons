"use strict";
// GPU-Konflikt-Wächter (Phase 10.1): vor dem Start eines Spiels oder Programms fragt die Oberfläche den Agenten und zeigt Konflikte als Dialog.
// Der Wächter verhindert nichts: „Trotzdem starten“ ist immer möglich. Fehler oder ein älterer Agent ohne Feature führen nie zu einer Sperre.
(function () {
  const $ = id => document.getElementById(id);
  const LABEL = { job_running: "KI-Job", game_running: "Spiel", program_running: "Programm", gpu_busy: "GPU belegt" };
  // Aktion je Konflikt (nur mit Schreibrecht sichtbar): beendet bzw. bricht ab, danach wird neu geprüft
  const FIX = {
    program_running: { label: "Beenden", path: c => "api/programs/" + encodeURIComponent(c.id) + "/stop", ask: c => c.name + " beenden?" },
    game_running: { label: "Beenden", path: c => "api/steam/games/" + c.id + "/stop", ask: c => c.name + " beenden? Nicht gespeicherter Fortschritt geht verloren." },
    job_running: { label: "Job abbrechen", path: c => "api/job/" + encodeURIComponent(c.id) + "/cancel", ask: c => "„" + c.name + "“ abbrechen?" },
  };

  async function check(kind, id) {
    try {
      const r = await fetch(pcq("api/guard?for=" + kind + (id ? "&id=" + encodeURIComponent(id) : "")), { headers: authHeaders() });
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }

  function paint(d, verb, state) {
    const box = $("guard_list");
    box.textContent = "";
    for (const c of d.conflicts) {
      const row = document.createElement("div"), txt = document.createElement("div"), kind = document.createElement("small"), name = document.createElement("b"), det = document.createElement("span");
      row.className = "gconf";
      kind.textContent = LABEL[c.kind] || c.kind; name.textContent = c.name; det.textContent = c.detail || "";
      txt.append(kind, name, det); row.append(txt);
      const fix = FIX[c.kind];
      if (fix && c.id != null) {
        const b = document.createElement("button");
        b.className = "stctl"; b.type = "button"; b.textContent = fix.label;
        b.onclick = async () => {
          if (!confirm(fix.ask(c))) return;
          b.disabled = true; $("guard_msg").textContent = "…";
          try {
            const r = await fetch(pcq(fix.path(c)), { method: "POST", headers: authHeaders() });
            if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || ("Fehler " + r.status));
            $("guard_msg").textContent = "Erledigt, prüfe neu …";
            await new Promise(res => setTimeout(res, 1500));
            const nd = await check(state.kind, state.id);
            if (!nd || nd.ok) { state.done(true); return; }           // nichts mehr im Weg: weiter mit dem Start
            paint(nd, verb, state); $("guard_msg").textContent = "";
          } catch (e) { $("guard_msg").textContent = e.message; b.disabled = false; }
        };
        row.append(b);
      }
      box.append(row);
    }
    $("guard_go").textContent = "Trotzdem " + verb;
  }

  // kind: "game" | "program"; verb z. B. „starten“. Gibt true zurück, wenn gestartet werden soll.
  window.pccGuard = async function (kind, id, name, verb) {
    if (typeof features === "undefined" || !features.includes("guard")) return true;
    const d = await check(kind, id);
    if (!d || d.ok) return true;
    verb = verb || "starten";
    return new Promise(resolve => {
      const sheet = $("guard_sheet");
      const state = { kind, id, done: v => { sheet.hidden = true; resolve(v); } };
      $("guard_title").textContent = "„" + (name || "Das") + "“ " + verb + "?";
      $("guard_msg").textContent = "";
      paint(d, verb, state);
      sheet.hidden = false;
      $("guard_go").onclick = () => state.done(true);
      $("guard_cancel").onclick = () => state.done(false);
      sheet.onclick = e => { if (e.target === sheet) state.done(false); };
    });
  };
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("guard_sheet").hidden) $("guard_cancel").click(); });
})();
