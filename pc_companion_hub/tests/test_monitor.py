"""Überwachung (Phase 10.7): Hänger-Erkennung, Gesundheitsmeldungen, Statistik."""
import asyncio
import json
import os
from datetime import date

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import notify, stats
from app.main import create_app

from tests.test_notify import Clock, clock, run  # noqa: F401


def snap(progress, gpu, state="running", jid="j1"):
    return {"gpu": {"util_pct": gpu}, "jobs": [{"job_id": jid, "tool": "ComfyUI", "title": "Bild", "state": state, "progress": progress}]}


def test_idle_gpu_and_frozen_progress_alerts_once_after_the_wait(clock):
    async def steps(n):
        n.on_snapshot("pc", "PC", snap(0.4, 1))
        clock.t += 19 * 60
        n.on_snapshot("pc", "PC", snap(0.4, 1))
        await asyncio.sleep(0)
        clock.t += 2 * 60
        n.on_snapshot("pc", "PC", snap(0.4, 2))
        n.on_snapshot("pc", "PC", snap(0.4, 2))                  # nicht doppelt
    sent = run({"notify_hang_min": 20}, steps)
    assert len(sent) == 1 and sent[0][0] == "KI-Job hängt vielleicht" and "21 Min." in sent[0][1]


def test_progress_or_gpu_activity_or_option_off_never_alert(clock):
    async def moving(n):
        for i in range(30):
            n.on_snapshot("pc", "PC", snap(i / 100, 0))
            clock.t += 120
    assert run({}, moving) == []

    async def busy(n):
        n.on_snapshot("pc", "PC", snap(0.4, 1))
        for _ in range(40):
            clock.t += 120
            n.on_snapshot("pc", "PC", snap(0.4, 90))             # GPU rechnet: kein Hänger
    assert run({}, busy) == []

    async def idle(n):
        n.on_snapshot("pc", "PC", snap(0.4, 0))
        clock.t += 3600
        n.on_snapshot("pc", "PC", snap(0.4, 0))
    assert run({"notify_hang_min": 0}, idle) == []
    assert len(run({"notify_hang_min": "kaputt"}, idle)) == 1     # ungültiger Wert: Standard 20


def test_finished_job_clears_tracking_and_a_busy_phase_restarts_the_wait(clock):
    async def steps(n):
        n.on_snapshot("pc", "PC", snap(0.4, 0))
        clock.t += 15 * 60
        n.on_snapshot("pc", "PC", snap(0.4, 80))                  # GPU kurz aktiv: Wartezeit beginnt neu
        clock.t += 15 * 60
        n.on_snapshot("pc", "PC", snap(0.4, 0))
        n.on_snapshot("pc", "PC", snap(0.4, 0, state="done"))
        assert n.recs["pc"]["hang"] == {}
    sent = run({}, steps)
    assert all(m[0] != "KI-Job hängt vielleicht" for m in sent)


def issue(i, level="warn", text="Text"):
    return {"id": i, "level": level, "text": text}


def test_health_issues_are_announced_once_then_daily_and_clear_when_gone(clock):
    async def steps(n):
        n.on_health("pc", "PC", [issue("reboot-pending"), issue("uptime"), issue("disk-full:C:", "bad", "C: voll")])
        n.on_health("pc", "PC", [issue("reboot-pending"), issue("disk-full:C:", "bad", "C: voll")])       # nicht nochmal
        clock.t += 86400 + 5
        n.on_health("pc", "PC", [issue("reboot-pending")])                                               # nach einem Tag wieder
        n.on_health("pc", "PC", [])                                                                      # behoben: vergessen
        n.on_health("pc", "PC", [issue("reboot-pending")])                                               # kommt zurück: sofort wieder
    sent = run({}, steps)
    titles = [(m[0], m[1]) for m in sent]
    assert titles.count(("Gesundheit: Hinweis", "PC: Text")) == 3
    assert ("Gesundheit: dringend", "PC: C: voll") in titles and len(sent) == 4                         # „uptime“ wird nie gemeldet
    assert all(m[2].startswith("pcc-pc-health-") for m in sent)


# ---------------------------------------------------------------- Statistik
def test_games_weekly_groups_by_monday_and_picks_the_top_game():
    today = date(2026, 11, 18)                                   # Mittwoch
    t = lambda d, h=12: __import__("datetime").datetime(2026, 11, d, h).timestamp()            # noqa: E731
    ev = [("CS2", t(16), t(16) + 3600), ("CS2", t(17), t(17) + 1800), ("Hades", t(17, 18), t(17, 18) + 600), ("Alt", t(2), t(2) + 7200)]
    w = stats.games_weekly(ev, today)
    assert len(w) == 8 and w[-1]["week"] == "2026-11-16" and w[-1]["minutes"] == 100 and w[-1]["top"] == "CS2" and w[-1]["top_minutes"] == 90
    assert w[-3]["week"] == "2026-11-02" and w[-3]["minutes"] == 120 and w[0]["minutes"] == 0 and w[0]["top"] is None


def test_job_trend_needs_five_runs_and_compares_recent_with_before():
    ev = [("a", "ComfyUI", 0, 60 * m) for m in (20, 20, 20, 10, 10, 10)]                         # neueste zuerst
    r = stats.job_trend(ev)
    assert r["trend"] == [{"tool": "ComfyUI", "recent_min": 20.0, "before_min": 10.0, "change_pct": 100, "n": 6}]
    assert stats.job_trend(ev[:4])["trend"] == [] and len(r["jobs"]) == 6 and r["jobs"][0]["minutes"] == 20.0


def test_usage_days_average_and_busy_minutes():
    today = date(2026, 11, 18)
    base = __import__("datetime").datetime(2026, 11, 18, 10).timestamp()
    samples = [(base + i * 30, g) for i, g in enumerate([0, 50, 100, None])] + [(__import__("datetime").datetime(2026, 11, 1).timestamp(), 99)]
    u = stats.usage_days(samples, today)
    assert len(u) == 14 and u[-1]["day"] == "2026-11-18" and u[-1]["gpu_avg"] == 50.0 and u[-1]["busy_min"] == 1 and u[-1]["online_min"] == 2
    assert u[0]["gpu_avg"] is None and all(x["day"] != "2026-11-01" for x in u)


OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "agent-secret"}]}


def test_endpoints_stats_and_health_check(tmp_path):
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        h = {"Authorization": "Bearer master"}
        d = c.get("/api/stats", headers=h).json()
        assert len(d["games_weekly"]) == 8 and len(d["usage"]) == 14 and d["jobs"] == {"jobs": [], "trend": []}
        assert c.get("/api/health-check", headers=h).json() == {"checked": None, "issues": [], "supported": False}
        assert c.get("/api/stats").status_code == 401 and c.get("/api/health-check").status_code == 401
