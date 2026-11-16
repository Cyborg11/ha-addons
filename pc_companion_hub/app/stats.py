"""Statistik (Phase 10.7): Spielzeit pro Woche, Dauer der KI-Jobs im Trend und Auslastung pro Tag.
Quellen sind die schon vorhandenen Datenbanken des Hubs (Strom-Ereignisse, Verlauf); es kommt nichts Neues dazu.
Spiele und Jobs erscheinen nur, wenn sie mindestens ``MIN_EVENT_WH`` Strom verbraucht haben (siehe energy.py) – sehr kurze Läufe fehlen also."""
from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

WEEKS = 8
BUSY_GPU_PCT = 20.0            # ab dieser GPU-Last gilt ein Messpunkt als „ausgelastet“
HISTORY_SAMPLE_S = 30


def _date(t: float, tz: tzinfo | None):
    return (datetime.fromtimestamp(t, tz) if tz else datetime.fromtimestamp(t)).date()


def today_in(tz: tzinfo | None):
    return datetime.now(tz).date() if tz else datetime.now().date()


def week_start(d):
    return d - timedelta(days=d.weekday())


def games_weekly(events: list[tuple], today, tz: tzinfo | None = None, weeks: int = WEEKS) -> list[dict]:
    """events: (name, t0, t1) → je Woche (Montag) Minuten insgesamt und das meistgespielte Spiel."""
    this = week_start(today)
    starts = [this - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    per: dict = {s: {} for s in starts}
    for name, t0, t1 in events:
        s = week_start(_date(t0, tz))
        if s in per:
            per[s][name] = per[s].get(name, 0.0) + max(0.0, (t1 - t0) / 60.0)
    out = []
    for s in starts:
        games = per[s]
        top = max(games.items(), key=lambda kv: kv[1]) if games else None
        out.append({"week": s.isoformat(), "minutes": round(sum(games.values())), "top": top[0] if top else None, "top_minutes": round(top[1]) if top else 0})
    return out


def job_trend(events: list[tuple]) -> dict:
    """events: (name, tool, t0, t1), neueste zuerst → die letzten Jobs und je Werkzeug „neueste 3“ gegen „davor“."""
    jobs = [{"name": n, "tool": tool, "start": t0, "minutes": round((t1 - t0) / 60, 1)} for n, tool, t0, t1 in events]
    by: dict[str, list[float]] = {}
    for j in jobs:
        by.setdefault(j["tool"] or "Job", []).append(j["minutes"])
    trend = []
    for tool, mins in by.items():
        if len(mins) < 5:
            continue
        recent, older = mins[:3], mins[3:]
        a, b = sum(recent) / len(recent), sum(older) / len(older)
        trend.append({"tool": tool, "recent_min": round(a, 1), "before_min": round(b, 1), "change_pct": round(100 * (a - b) / b) if b > 0 else None, "n": len(mins)})
    return {"jobs": jobs[:12], "trend": trend}


def usage_days(samples: list[tuple], today, tz: tzinfo | None = None, days: int = 14) -> list[dict]:
    """samples: (t, gpu) → je Tag mittlere GPU-Last und Minuten mit mindestens 20 % Last."""
    first = today - timedelta(days=days - 1)
    acc: dict = {}
    for t, gpu in samples:
        if gpu is None:
            continue
        d = _date(t, tz)
        if d < first or d > today:
            continue
        a = acc.setdefault(d, [0, 0.0, 0])
        a[0] += 1
        a[1] += gpu
        a[2] += gpu >= BUSY_GPU_PCT
    out = []
    for i in range(days):
        d = first + timedelta(days=i)
        n, s, busy = acc.get(d, (0, 0.0, 0))
        out.append({"day": d.isoformat(), "gpu_avg": round(s / n, 1) if n else None, "busy_min": round(busy * HISTORY_SAMPLE_S / 60), "online_min": round(n * HISTORY_SAMPLE_S / 60)})
    return out
