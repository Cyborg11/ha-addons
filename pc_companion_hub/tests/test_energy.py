"""Strom und Kosten (Phase 10.6): Leistung -> kWh, Zuordnung zu Tag/Job/Spiel, Kosten, Persistenz, Endpunkt, HA-Sensoren."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

os.environ["HUB_NO_AUTOCREATE"] = "1"

import httpx
import pytest
from fastapi.testclient import TestClient

from app import energy as en
from app import notify
from app.main import create_app

TZ = timezone(timedelta(hours=1))
MASTER = {"Authorization": "Bearer master"}
T0 = datetime(2026, 11, 16, 12, 0, 0, tzinfo=TZ).timestamp()


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def snap(gpu=300.0, cpu=None, jobs=None, game=None):
    s = {"gpu": {"power_w": gpu, "util_pct": 90}}
    if cpu is not None:
        s["sensors"] = {"cpu_power_w": cpu}
    if jobs is not None:
        s["jobs"] = jobs
    if game:
        s["steam"] = {"running": game, "downloading": None}
    return s


@pytest.fixture()
def rig(tmp_path):
    clock = Clock()
    meter = en.EnergyMeter(tmp_path / "e.db", TZ, clock)
    return clock, meter


def run(clock, meter, seconds, **kw):
    for _ in range(int(seconds)):
        clock.t += 1
        meter.feed("pc", snap(**kw))


# ---------------------------------------------------------------- Messwerte
@pytest.mark.parametrize("s,expect", [
    ({"gpu": {"power_w": 300}}, (300.0, False)), ({"gpu": {"power_w": 300}, "sensors": {"cpu_power_w": 48.5}}, (348.5, True)), ({"sensors": {"cpu_power_w": 50}}, (50.0, True)),
    ({"gpu": {"power_w": None}}, (None, False)), ({}, (None, False)), ({"gpu": {"power_w": -5}}, (None, False)), ({"gpu": {"power_w": 99999}}, (None, False)),
    ({"gpu": {"power_w": True}}, (None, False)), ({"gpu": {"power_w": "300"}}, (None, False)), ({"gpu": {"power_w": 100}, "sensors": {"cpu_power_w": "x"}}, (100.0, False))])
def test_power_parsing(s, expect):
    assert en.power_w(s) == expect


def test_constant_power_integrates_to_the_right_kwh(rig):
    clock, meter = rig
    meter.feed("pc", snap())                                                                              # erster Messwert: nur Startpunkt
    run(clock, meter, 3600, gpu=300.0, cpu=100.0)                                                         # 400 W eine Stunde lang
    s = meter.summary("pc", 30.0)
    assert s["today"]["kwh"] == pytest.approx(0.4, abs=0.002) and s["today"]["eur"] == pytest.approx(0.12, abs=0.001)
    assert s["coverage"] == "GPU + CPU" and s["week"]["kwh"] == s["month"]["kwh"] == s["today"]["kwh"]
    assert meter.today("pc") == pytest.approx(0.4, abs=0.002)


def test_gaps_and_missing_values_are_not_extrapolated(rig):
    clock, meter = rig
    meter.feed("pc", snap())
    clock.t += 3600                                                                                       # eine Stunde nichts gehört (PC aus, Hub neu gestartet)
    meter.feed("pc", snap())
    assert meter.summary("pc")["today"]["kwh"] == 0
    clock.t += 1
    meter.feed("pc", {"gpu": {"power_w": None}})                                                          # keine Leistung gemeldet
    clock.t += 1
    meter.feed("pc", snap(gpu=3600.0))
    assert meter.summary("pc")["today"]["kwh"] == pytest.approx(0.001, abs=1e-6)                         # nur die letzte Sekunde: 3600 W * 1 s = 1 Wh
    assert meter.summary("pc")["coverage"] == "nur GPU" and meter.summary("pc")["today"]["eur"] is None  # ohne Preis keine Kosten


def test_a_new_day_starts_a_new_total(rig):
    clock, meter = rig
    meter.feed("pc", snap())
    run(clock, meter, 600)
    clock.t = datetime(2026, 11, 16, 23, 59, 0, tzinfo=TZ).timestamp()
    meter.feed("pc", snap())
    run(clock, meter, 120)                                                                                # über Mitternacht
    s = meter.summary("pc", 10.0, days=3)
    assert [d["day"] for d in s["days"]] == ["2026-11-15", "2026-11-16", "2026-11-17"]
    assert s["days"][0]["kwh"] == 0 and s["days"][1]["kwh"] > 0.05 and s["days"][2]["kwh"] > 0 and s["today"]["day"] == "2026-11-17"
    assert s["yesterday"]["day"] == "2026-11-16" and s["week"]["kwh"] == pytest.approx(sum(d["kwh"] for d in s["days"]), abs=0.002)
    assert s["month"]["kwh"] == s["week"]["kwh"]


def test_energy_goes_to_the_running_job_and_game_and_short_runs_are_dropped(rig):
    clock, meter = rig
    meter.feed("pc", snap())
    job = {"job_id": "j1", "state": "running", "tool": "SIG", "title": "Portrait"}
    run(clock, meter, 600, gpu=200.0, jobs=[job])                                                         # 10 min bei 200 W = 33,3 Wh
    run(clock, meter, 5, gpu=200.0, jobs=[{**job, "state": "done"}])                                      # Job zu Ende
    run(clock, meter, 3, gpu=100.0, jobs=[{"job_id": "j2", "state": "running", "tool": "SIG", "title": "kurz"}])
    run(clock, meter, 2, gpu=100.0, jobs=[])                                                              # nur wenige Sekunden: unter der Mindestmenge
    run(clock, meter, 1200, gpu=300.0, game={"appid": 730, "name": "Counter-Strike 2", "since": 1})      # 20 min bei 300 W = 100 Wh
    run(clock, meter, 2, gpu=50.0)
    s = meter.summary("pc", 40.0)
    assert [(j["name"], j["tool"]) for j in s["jobs"]] == [("Portrait", "SIG")] and s["jobs"][0]["kwh"] == pytest.approx(0.0333, abs=0.001)
    assert s["jobs"][0]["minutes"] == 10 and s["jobs"][0]["eur"] == pytest.approx(0.01, abs=0.005)
    assert [g["name"] for g in s["games"]] == ["Counter-Strike 2"] and s["games"][0]["kwh"] == pytest.approx(0.1, abs=0.002) and s["games"][0]["tool"] is None
    assert s["today"]["kwh"] > s["jobs"][0]["kwh"] + s["games"][0]["kwh"]                                  # der Tag enthält auch den Rest


def test_two_running_jobs_are_not_double_counted(rig):
    clock, meter = rig
    meter.feed("pc", snap())
    jobs = [{"job_id": "a", "state": "running", "tool": "SIG", "title": "A"}, {"job_id": "b", "state": "running", "tool": "SIG", "title": "B"}]
    run(clock, meter, 1800, gpu=200.0, jobs=jobs)
    run(clock, meter, 1, gpu=0.0, jobs=[])
    s = meter.summary("pc")
    assert len(s["jobs"]) == 1 and s["jobs"][0]["name"] == "A" and s["jobs"][0]["kwh"] <= s["today"]["kwh"] + 1e-6


def test_data_survives_a_restart_and_pcs_are_separate(tmp_path):
    clock = Clock()
    m1 = en.EnergyMeter(tmp_path / "e.db", TZ, clock)
    m1.feed("a", snap())
    m1.feed("b", snap(gpu=100.0))
    for _ in range(600):
        clock.t += 1
        m1.feed("a", snap(gpu=300.0))
        m1.feed("b", snap(gpu=100.0))
    m1.flush()
    m2 = en.EnergyMeter(tmp_path / "e.db", TZ, clock)
    assert m2.summary("a")["today"]["kwh"] == pytest.approx(0.05, abs=0.001) and m2.summary("b")["today"]["kwh"] == pytest.approx(0.0167, abs=0.001)
    assert m2.summary("nix")["today"]["kwh"] == 0
    m2.flush()
    m2.flush()
    assert m2.summary("a")["today"]["kwh"] == pytest.approx(0.05, abs=0.001)                               # mehrfaches Schreiben verdoppelt nichts


def test_old_events_and_days_are_pruned(tmp_path):
    clock = Clock()
    m = en.EnergyMeter(tmp_path / "e.db", TZ, clock)
    m.db.execute("INSERT INTO energy_event VALUES ('pc','job','alt','SIG',?,?,50.0)", [int(T0 - 200 * 86400), int(T0 - 200 * 86400 + 600)])
    m.db.execute("INSERT INTO energy_day VALUES ('pc',?,5000.0,0)", [(datetime.fromtimestamp(T0 - 500 * 86400, TZ)).date().isoformat()])
    m.db.commit()
    clock.t += 1000
    m.flush()
    assert m.db.execute("SELECT COUNT(*) FROM energy_event").fetchone()[0] == 0 and m.db.execute("SELECT COUNT(*) FROM energy_day").fetchone()[0] == 0


def test_unusable_database_disables_the_meter_quietly(tmp_path):
    bad = tmp_path / "ordner"
    bad.mkdir()
    m = en.EnergyMeter(bad / ".." / "ordner", TZ, Clock())                                                # ein Ordner statt einer Datei
    m.feed("pc", snap())
    m.feed("pc", snap())
    assert m.summary("pc")["today"]["kwh"] == 0


def test_summary_limits(rig):
    clock, meter = rig
    assert len(meter.summary("pc", days=1)["days"]) == 1 and len(meter.summary("pc", days=9999)["days"]) == 120 and len(meter.summary("pc", days=-5)["days"]) == 1


# ---------------------------------------------------------------- Endpunkt und HA
OPTS = {"ui_token": "master", "strompreis_ct_kwh": 32.5, "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "t"}]}


def test_energy_endpoint_needs_login_is_readable_by_view_devices_and_uses_the_price(tmp_path):
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        assert c.get("/api/energy").status_code == 401
        code = c.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
        v = {"Authorization": "Bearer " + c.post("/api/pair/redeem", json={"code": code}).json()["token"]}
        r = c.get("/api/energy?days=7", headers=v)
        assert r.status_code == 200
        d = r.json()
        assert d["price_ct_kwh"] == 32.5 and len(d["days"]) == 7 and d["today"]["kwh"] == 0 and d["jobs"] == [] and d["coverage"] == "nur GPU"
    for bad in (-1, "x", 9999, None):
        o = json.loads(json.dumps(OPTS))
        o["strompreis_ct_kwh"] = bad
        with TestClient(create_app(o, data_dir=tmp_path)) as c:
            assert c.get("/api/energy", headers=MASTER).json()["price_ct_kwh"] in (None, 200.0)           # Unsinn wird zu 0 (kein Preis) bzw. auf 200 begrenzt


def test_ha_sensor_states_are_only_written_for_sensor_entities():
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), json.loads(req.content), req.headers["authorization"]))
        return httpx.Response(200, json={})

    ha = notify.HaNotifier("notify.x", "tok", "http://ha/api", transport=httpx.MockTransport(handler))
    assert asyncio.run(ha.set_state("sensor.pc_companion_gaming_pc_kwh_heute", 1.234, {"unit_of_measurement": "kWh"})) is True
    assert seen == [("http://ha/api/states/sensor.pc_companion_gaming_pc_kwh_heute", {"state": 1.234, "attributes": {"unit_of_measurement": "kWh"}}, "Bearer tok")]
    for bad in ("light.wohnzimmer", "sensor.", "sensor.A", "../x", "sensor.a/b", ""):
        assert asyncio.run(ha.set_state(bad, 1, {})) is False
    assert len(seen) == 1 and asyncio.run(notify.HaNotifier("notify.x", None).set_state("sensor.x", 1, {})) is False
