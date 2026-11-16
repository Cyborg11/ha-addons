"""Strom und Kosten (Phase 10.6): der Hub summiert die Leistung von GPU (NVML) und CPU (LibreHardwareMonitor) zu kWh.

Wichtig: Gemessen wird nur, was GPU und CPU melden. Mainboard, Lüfter, Netzteil-Verluste, Laufwerke und Peripherie fehlen – die Zahl ist eine
**Untergrenze/Schätzung**, keine Zählermessung. Zuordnung: der Verbrauch geht auf den Tag und, solange es läuft, auf den laufenden KI-Job und das laufende Steam-Spiel.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

log = logging.getLogger("pc-companion-hub")

MAX_GAP_S = 10.0               # größere Lücken zwischen zwei Messwerten (PC aus, Hub neu gestartet) werden nicht hochgerechnet
FLUSH_S = 60.0
EVENT_KEEP_DAYS = 90
DAY_KEEP_DAYS = 400
MIN_EVENT_WH = 0.2             # kürzere/sparsamere Läufe werden nicht als eigener Eintrag gespeichert


def power_w(snap: dict) -> tuple[float | None, bool]:
    """(Summe der gemessenen Leistung in W, CPU-Leistung war dabei). None, wenn nichts gemessen wurde."""
    g = (snap.get("gpu") or {}).get("power_w")
    c = (snap.get("sensors") or {}).get("cpu_power_w")
    vals = [v for v in (g, c) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 5000]
    return (float(sum(vals)), isinstance(c, (int, float)) and not isinstance(c, bool)) if vals else (None, False)


class EnergyMeter:
    def __init__(self, path: str | Path, tz: tzinfo | None = None, clock=time.time):
        self.path, self.tz, self.clock = Path(path), tz, clock
        self._lock = threading.Lock()
        self._st: dict[str, dict] = {}
        self._pending_day: dict[tuple[str, str], float] = {}
        self._cpu_seen: dict[str, bool] = {}
        self._last_flush = 0.0
        self.db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(self.path), check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS energy_day (pc TEXT, day TEXT, wh REAL, cpu INTEGER DEFAULT 0, PRIMARY KEY (pc, day))")
            self.db.execute("CREATE TABLE IF NOT EXISTS energy_event (pc TEXT, kind TEXT, name TEXT, tool TEXT, t0 INTEGER, t1 INTEGER, wh REAL)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_energy_event ON energy_event (pc, kind, t1)")
            self.db.commit()
        except (OSError, sqlite3.Error) as e:
            log.warning("Strom-Datenbank nicht nutzbar (%s) – Stromzähler deaktiviert", e)
            self.db = None

    # ---- Erfassen
    def _day(self, t: float) -> str:
        return datetime.fromtimestamp(t, self.tz).date().isoformat() if self.tz else datetime.fromtimestamp(t).date().isoformat()

    def feed(self, pc: str, snap: dict) -> None:
        """Bei jedem Snapshot aufrufen. Rechnet die Zeit seit dem letzten Messwert (höchstens MAX_GAP_S) in Wh um."""
        if self.db is None or not snap:
            return
        t = self.clock()
        w, cpu = power_w(snap)
        with self._lock:
            st = self._st.setdefault(pc, {"t": None, "job": None, "game": None})
            dt = t - st["t"] if st["t"] is not None else 0.0
            st["t"] = t
            jobs = [j for j in (snap.get("jobs") or ([snap["job"]] if snap.get("job") else [])) if isinstance(j, dict) and j.get("state") == "running"]
            run = ((snap.get("steam") or {}).get("running")) or None
            self._track(pc, st, "job", ({"key": str(jobs[0].get("job_id") or ""), "name": jobs[0].get("title") or jobs[0].get("tool") or "KI-Job", "tool": jobs[0].get("tool")}
                                        if jobs and jobs[0].get("job_id") else None), t)
            self._track(pc, st, "game", ({"key": str(run.get("appid")), "name": run.get("name") or "Spiel", "tool": None} if run and run.get("appid") else None), t)
            if w is not None and 0 < dt <= MAX_GAP_S:
                wh = w * dt / 3600.0
                key = (pc, self._day(t))
                self._pending_day[key] = self._pending_day.get(key, 0.0) + wh
                if cpu:
                    self._cpu_seen[pc] = True
                for kind in ("job", "game"):
                    if st[kind]:
                        st[kind]["wh"] += wh
            if t - self._last_flush >= FLUSH_S:
                self._flush_locked(t)

    def _track(self, pc: str, st: dict, kind: str, cur: dict | None, t: float) -> None:
        old = st[kind]
        if old and (not cur or cur["key"] != old["key"]):
            self._close(pc, kind, old, t)
            old = st[kind] = None
        if cur and not old:
            st[kind] = {**cur, "t0": t, "wh": 0.0}

    def _close(self, pc: str, kind: str, ev: dict, t: float) -> None:
        if ev["wh"] < MIN_EVENT_WH:
            return
        try:
            self.db.execute("INSERT INTO energy_event VALUES (?,?,?,?,?,?,?)", [pc, kind, str(ev["name"])[:100], ev.get("tool"), int(ev["t0"]), int(t), ev["wh"]])
            self.db.commit()
        except sqlite3.Error as e:
            log.warning("Stromdaten nicht schreibbar: %s", e)

    def flush(self) -> None:
        with self._lock:
            self._flush_locked(self.clock())

    def _flush_locked(self, t: float) -> None:
        self._last_flush = t
        try:
            for (pc, day), wh in self._pending_day.items():
                self.db.execute("INSERT INTO energy_day (pc, day, wh, cpu) VALUES (?,?,?,?) ON CONFLICT(pc, day) DO UPDATE SET wh = wh + excluded.wh, "
                                "cpu = MAX(cpu, excluded.cpu)", [pc, day, wh, 1 if self._cpu_seen.get(pc) else 0])
            self._pending_day.clear()
            self.db.execute("DELETE FROM energy_event WHERE t1 < ?", [int(t - EVENT_KEEP_DAYS * 86400)])
            self.db.execute("DELETE FROM energy_day WHERE day < ?", [self._day(t - DAY_KEEP_DAYS * 86400)])
            self.db.commit()
        except sqlite3.Error as e:
            log.warning("Stromdaten nicht schreibbar: %s", e)

    # ---- Abfragen
    def _day_wh(self, pc: str) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.db is None:
            return out
        try:
            for day, wh in self.db.execute("SELECT day, wh FROM energy_day WHERE pc = ?", [pc]):
                out[day] = wh
        except sqlite3.Error:
            return out
        for (p, day), wh in self._pending_day.items():
            if p == pc:
                out[day] = out.get(day, 0.0) + wh
        return out

    def today(self, pc: str) -> float:
        """kWh seit Mitternacht (Zeitzone des Hubs)."""
        with self._lock:
            return self._day_wh(pc).get(self._day(self.clock()), 0.0) / 1000.0

    def summary(self, pc: str, price_ct_kwh: float = 0.0, days: int = 30, events: int = 8) -> dict:
        days = max(1, min(int(days), 120))
        with self._lock:
            per = self._day_wh(pc)
            now = self.clock()
            cpu = self._cpu_seen.get(pc, False)
            ev = {"job": [], "game": []}
            if self.db is not None:
                try:
                    for kind in ev:
                        for name, tool, t0, t1, wh in self.db.execute("SELECT name, tool, t0, t1, wh FROM energy_event WHERE pc = ? AND kind = ? ORDER BY t1 DESC LIMIT ?", [pc, kind, events]):
                            ev[kind].append((name, tool, t0, t1, wh))
                    cpu = cpu or bool(self.db.execute("SELECT MAX(cpu) FROM energy_day WHERE pc = ?", [pc]).fetchone()[0])
                except sqlite3.Error:
                    pass
        eur = (lambda kwh: round(kwh * price_ct_kwh / 100.0, 2)) if price_ct_kwh > 0 else (lambda kwh: None)
        today_d = datetime.fromtimestamp(now, self.tz).date() if self.tz else datetime.fromtimestamp(now).date()
        series = []
        for i in range(days - 1, -1, -1):
            d = (today_d - timedelta(days=i)).isoformat()
            kwh = per.get(d, 0.0) / 1000.0
            series.append({"day": d, "kwh": round(kwh, 4), "eur": eur(kwh)})

        def total(from_day: str) -> dict:
            kwh = sum(v for d, v in per.items() if d >= from_day) / 1000.0
            return {"kwh": round(kwh, 4), "eur": eur(kwh)}

        def one(name, tool, t0, t1, wh):
            kwh = wh / 1000.0
            return {"name": name, "tool": tool, "start": t0, "minutes": round((t1 - t0) / 60), "kwh": round(kwh, 4), "eur": eur(kwh)}

        return {"price_ct_kwh": price_ct_kwh or None, "coverage": "GPU + CPU" if cpu else "nur GPU",
                "today": series[-1] if series else {"kwh": 0, "eur": eur(0)}, "yesterday": series[-2] if len(series) > 1 else None,
                "week": total((today_d - timedelta(days=6)).isoformat()), "month": total(today_d.replace(day=1).isoformat()),
                "days": series, "jobs": [one(*e) for e in ev["job"]], "games": [one(*e) for e in ev["game"]]}
