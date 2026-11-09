"use strict";
// Top 5 der Programme nach GPU, CPU, RAM, Festplatte und Netzwerk (Dashboard). Der Agent misst auf Anfrage (2-4 s),
// deshalb wird nur aktualisiert, solange der Bereich aufgeklappt und sichtbar ist.
(function () {
  const $ = id => document.getElementById(id);
  const box = $("top_box");
  if (!box) return;

  const num = (v, d) => v.toLocaleString("de-DE", { maximumFractionDigits: d == null ? 0 : d });
  const rate = b => b >= 1048576 ? num(b / 1048576, 1) + " MB/s" : num(b / 1024, 0) + " KB/s";
  const KINDS = [
    { k: "gpu", label: "GPU", val: r => r.gpu_pct, text: r => num(r.gpu_pct, 0) + " %" + (r.vram_mb ? " · " + num(r.vram_mb) + " MB VRAM" : ""), max: 100 },
    { k: "cpu", label: "CPU", val: r => r.cpu, text: r => num(r.cpu, 1) + " %", max: 100 },
    { k: "ram", label: "RAM", val: r => r.ram_mb, text: r => r.ram_mb >= 1024 ? num(r.ram_mb / 1024, 1) + " GB" : num(r.ram_mb) + " MB" },
    { k: "disk", label: "Festplatte", val: r => r.io_bps, text: r => rate(r.io_bps) + " (L " + rate(r.read_bps) + " · S " + rate(r.write_bps) + ")" },
    { k: "net", label: "Netzwerk", val: r => r.conns, text: r => r.conns + (r.conns === 1 ? " Verbindung" : " Verbindungen") },
  ];
  const HINT = {
    gpu: "Auslastung der am stärksten beanspruchten GPU-Engine des Programms.",
    cpu: "Anteil an der Gesamt-CPU. Gleichnamige Prozesse (z. B. Browser) sind zusammengefasst.",
    ram: "Belegter Arbeitsspeicher (Working Set), gleichnamige Prozesse zusammengefasst.",
    disk: "Lesen und Schreiben von Dateien und Geräten pro Sekunde (L = gelesen, S = geschrieben).",
    net: "Die Datenmenge je Programm liefert Windows nur mit Administratorrechten. Ohne sie zeigt die Liste die Programme mit den meisten aktiven Verbindungen ins Netz, darunter den Gesamtdurchsatz der Netzwerkkarte.",
  };
  let kind = store.get("pcc_top_kind") || "gpu";
  if (!KINDS.some(x => x.k === kind)) kind = "gpu";
  let data = null, busy = false;

  function render() {
    const seg = $("top_kinds");
    seg.textContent = "";
    for (const x of KINDS) {
      const b = document.createElement("button");
      b.className = "segbtn" + (x.k === kind ? " on" : "");
      b.textContent = x.label;
      b.onclick = () => { kind = x.k; store.set("pcc_top_kind", kind); render(); };
      seg.append(b);
    }
    const cur = KINDS.find(x => x.k === kind);
    const list = $("top_list");
    list.textContent = "";
    $("top_hint").textContent = HINT[kind];
    if (!data) { list.textContent = busy ? "Messe …" : ""; list.className = "muted"; return; }
    const rows = kind === "net" ? data.net.items : data[kind];
    if (kind === "gpu" && !data.gpu_available) { list.textContent = "Dieser PC liefert keine GPU-Daten je Programm."; list.className = "muted"; return; }
    if (!rows.length) { list.textContent = kind === "net" ? "Keine aktiven Verbindungen ins Netz." : "Nichts Auffälliges."; list.className = "muted"; return; }
    list.className = "";
    const top = Math.max(...rows.map(cur.val), 1), scale = cur.max || top;
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "toprow";
      const name = document.createElement("div");
      const b = document.createElement("b");
      b.textContent = r.name;
      name.append(b);
      if (r.count > 1) { const c = document.createElement("small"); c.className = "muted"; c.textContent = " ×" + r.count; name.append(c); }
      const v = document.createElement("span");
      v.textContent = cur.text(r);
      const bar = document.createElement("div");
      bar.className = "bar";
      const i = document.createElement("i");
      i.style.width = Math.max(2, Math.min(100, cur.val(r) / scale * 100)) + "%";
      bar.append(i);
      row.append(name, v, bar);
      list.append(row);
    }
    if (kind === "net") {
      const t = document.createElement("div");
      t.className = "muted small";
      t.textContent = "Netzwerkkarte insgesamt: " + rate(data.net.total_bps);
      list.append(t);
    }
  }

  async function load() {
    if (busy || !features.includes("top5") || !box.open) return;
    busy = true;
    if (!data) render();
    try {
      const r = await fetch(pcq("api/top?n=5"), { headers: authHeaders() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || ("Fehler " + r.status));
      data = d;
      $("top_msg").textContent = "";
    } catch (e) { $("top_msg").textContent = e.message; }
    busy = false;
    render();
  }

  box.addEventListener("toggle", load);
  $("top_reload").onclick = load;
  window.addEventListener("pcc:pc", () => { data = null; render(); load(); });
  setInterval(() => { if (box.open && !$("live").hidden && !document.hidden && !box.closest(".view").hidden) load(); }, 8000);
  render();
})();
