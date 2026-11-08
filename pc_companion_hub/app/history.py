"""Langzeitverlauf: der Hub speichert alle 30 s je PC einen gemittelten Messwert (SQLite, 14 Tage)."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("pc-companion-hub")

SAMPLE_S = 30                  # Schreibintervall je PC
RETENTION_S = 14 * 86400
PURGE_EVERY_S = 3600
MAX_POINTS = 240               # so viele Punkte liefert eine Abfrage höchstens
RANGES_H = (1, 6, 24, 168)
# Spalte -> (Aggregat in der Abfrage, Quelle im Snapshot)
METRICS = ("gpu", "temp", "power", "vram", "cpu", "ram")


def now() -> float:
    return time.time()


def extract(snap: dict) -> dict[str, float | None]:
    """Die gespeicherten Kennzahlen aus einem Agent-Snapshot (fehlende Werte = None)."""
    g, c, r = snap.get("gpu") or {}, snap.get("cpu") or {}, snap.get("ram") or {}
    vf = (100 * g["vram_used_mb"] / g["vram_total_mb"]) if g.get("vram_total_mb") and g.get("vram_used_mb") is not None else None
    rf = (100 * r["used_mb"] / r["total_mb"]) if r.get("total_mb") and r.get("used_mb") is not None else None
    return {"gpu": g.get("util_pct"), "temp": g.get("temp_c"), "power": g.get("power_w"), "vram": vf,
            "cpu": c.get("util_pct"), "ram": rf}


class History:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._acc: dict[str, dict] = {}        # pc -> laufender Mittelwert
        self._last_purge = 0.0
        self.db = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(self.path), check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS samples (pc TEXT, t INTEGER, gpu REAL, temp REAL, power REAL, vram REAL, cpu REAL, ram REAL)")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_samples ON samples (pc, t)")
            self.db.commit()
        except (OSError, sqlite3.Error) as e:
            log.warning("Verlaufsdatenbank nicht nutzbar (%s) – Langzeitverlauf deaktiviert", e)
            self.db = None

    def feed(self, pc: str, snap: dict) -> None:
        """Wird bei jedem Snapshot aufgerufen; schreibt höchstens alle SAMPLE_S Sekunden eine Zeile."""
        if self.db is None or not snap:
            return
        t = now()
        vals = extract(snap)
        with self._lock:
            a = self._acc.setdefault(pc, {"start": t, "n": {m: 0 for m in METRICS}, "sum": {m: 0.0 for m in METRICS}, "max": {}})
            for m, v in vals.items():
                if v is not None:
                    a["n"][m] += 1
                    a["sum"][m] += v
                    a["max"][m] = max(a["max"].get(m, v), v)
            if t - a["start"] < SAMPLE_S:
                return
            # Temperatur und Leistung als Spitzenwert, der Rest als Mittelwert: so verschwinden kurze Spitzen nicht
            row = [(a["max"].get(m) if m in ("temp", "power") else (a["sum"][m] / a["n"][m] if a["n"][m] else None)) for m in METRICS]
            self._acc.pop(pc, None)
            try:
                self.db.execute("INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)", [pc, int(t), *row])
                if t - self._last_purge > PURGE_EVERY_S:
                    self.db.execute("DELETE FROM samples WHERE t < ?", [int(t - RETENTION_S)])
                    self._last_purge = t
                self.db.commit()
            except sqlite3.Error as e:
                log.warning("Verlauf nicht schreibbar: %s", e)

    def query(self, pc: str, hours: float) -> dict:
        hours = min(max(hours, 0.25), RETENTION_S / 3600)
        if self.db is None:
            return {"points": [], "bucket_s": SAMPLE_S, "hours": hours}
        t = now()
        span = hours * 3600
        bucket = max(SAMPLE_S, int(span / MAX_POINTS))
        with self._lock:
            rows = self.db.execute(
                "SELECT (t / ?) * ? AS b, AVG(gpu), MAX(temp), MAX(power), AVG(vram), AVG(cpu), AVG(ram) "
                "FROM samples WHERE pc = ? AND t >= ? GROUP BY b ORDER BY b",
                [bucket, bucket, pc, int(t - span)],
            ).fetchall()
        pts = [{"t": r[0], **{m: (round(v, 1) if v is not None else None) for m, v in zip(METRICS, r[1:])}} for r in rows]
        return {"points": pts, "bucket_s": bucket, "hours": hours}
