"use strict";
// Aktionen: schicken POST /api/action/<name> an den Hub (relative URL wegen Ingress/Proxy).
(function () {
  const msg = t => { document.getElementById("actmsg").textContent = t; };
  const getToken = () => { try { return localStorage.getItem("pcc_ui_token") || ""; } catch (e) { return ""; } };

  async function act(name, body, label) {
    msg("…");
    try {
      const r = await fetch(pcq("api/action/" + name), {
        method: "POST",
        headers: { Authorization: "Bearer " + getToken(), "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { msg("Fehler: " + (d.detail || r.status)); return null; }
      msg((label || name) + " ✓");
      return d;
    } catch (e) { msg("Hub nicht erreichbar"); return null; }
  }

  document.querySelectorAll("button[data-act]").forEach(b => {
    b.onclick = async () => {
      const q = b.dataset.confirm;
      if (q && !confirm(q)) return;
      const d = await act(b.dataset.act, {}, b.textContent);
      if (d && d.muted !== undefined) msg(d.muted ? "Stumm ✓" : "Ton an ✓");
    };
  });

  const vol = document.getElementById("vol"), volval = document.getElementById("volval");
  vol.oninput = () => { volval.textContent = vol.value; };
  vol.onchange = () => act("volume", { level: Number(vol.value) }, "Lautstärke");
  document.querySelectorAll("button[data-vol]").forEach(b => {
    b.onclick = async () => {
      const d = await act("volume", { delta: Number(b.dataset.vol) }, "Lautstärke");
      if (d && d.level !== undefined) { vol.value = d.level; volval.textContent = d.level; }
    };
  });

  document.getElementById("openurl").onclick = async () => {
    const u = document.getElementById("url");
    if (await act("open_url", { url: u.value.trim() }, "Link geöffnet")) u.value = "";
  };
})();
