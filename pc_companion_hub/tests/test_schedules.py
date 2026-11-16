"""Zeitpläne (Phase 10.5): Prüfung, Speicher, Fälligkeit mit gefälschter Uhr, Überspringen, „Energiesparmodus, wenn nichts läuft“, Endpunkte."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import scenes as sc
from app import schedules as sch
from app.hub import Hub
from app.main import create_app

TZ = timezone(timedelta(hours=1))
MASTER = {"Authorization": "Bearer master"}
MONDAY = datetime(2026, 11, 16, 7, 30, tzinfo=TZ)                          # ein Montag


def raw(**kw):
    base = {"name": "Morgens", "days": [0, 1, 2, 3, 4], "time": "07:30", "action": {"type": "wake"}}
    base.update(kw)
    return base


# ---------------------------------------------------------------- Prüfung
def test_a_valid_schedule_is_cleaned_and_described():
    s = sch.clean_schedule(raw(days=[4, 0, 0, 2], pc="gaming-pc"))
    assert s["days"] == [0, 2, 4] and s["pc"] == "gaming-pc" and s["enabled"] is True and s["id"].startswith("morgens-")
    assert sch.describe(sch.clean_schedule(raw())) == "Mo–Fr um 07:30: PC aufwecken"
    assert sch.describe(sch.clean_schedule(raw(days=list(range(7)), action={"type": "standby_if_idle"}))) == "täglich um 07:30: Energiesparmodus, wenn nichts läuft"
    assert sch.describe(sch.clean_schedule(raw(days=[5, 6]))) == "Sa, So um 07:30: PC aufwecken" and sch.describe(sch.clean_schedule(raw(days=[1, 3]))) == "Di, Do um 07:30: PC aufwecken"
    idle = sch.clean_schedule(raw(action={"type": "standby_if_idle"}))["action"]
    assert idle == {"type": "standby_if_idle", "idle_minutes": 10, "window_minutes": 120, "mode": "standby"}
    assert sch.is_critical(sch.clean_schedule(raw(action={"type": "standby_if_idle"}))) and not sch.is_critical(sch.clean_schedule(raw()))


@pytest.mark.parametrize("bad", [
    None, "x", {}, raw(name=""), raw(name="   "), raw(days=[]), raw(days=[7]), raw(days=[-1]), raw(days=["0"]), raw(days=[True]), raw(days="Mo"), raw(time="7:30"), raw(time="24:00"),
    raw(time="07:60"), raw(time="07:30:00"), raw(time=730), raw(action={"type": "format_c"}), raw(action="wake"), raw(action={}),
    raw(action={"type": "scene"}), raw(action={"type": "scene", "scene_id": "../x"}), raw(action={"type": "standby_if_idle", "idle_minutes": 0}),
    raw(action={"type": "standby_if_idle", "idle_minutes": 121}), raw(action={"type": "standby_if_idle", "window_minutes": 9}),
    raw(action={"type": "standby_if_idle", "mode": "hibernate"}), raw(action={"type": "standby_if_idle", "idle_minutes": 5.5}), raw(pc="../x")])
def test_invalid_schedules_are_rejected(bad):
    with pytest.raises(sch.ScheduleError):
        sch.clean_schedule(bad)


def test_unknown_fields_never_survive():
    s = sch.clean_schedule({**raw(), "cmd": "calc.exe", "action": {"type": "wake", "cmd": "x"}})
    assert set(s) == {"id", "name", "enabled", "days", "time", "action"} and s["action"] == {"type": "wake"}


# ---------------------------------------------------------------- Speicher
def test_store_persists_state_limits_and_survives_garbage(tmp_path):
    p = tmp_path / "schedules.json"
    st = sch.ScheduleStore(p)
    a = st.create(raw())
    st.mark(a["id"], last_run="2026-11-16", skip_date="2026-11-17")
    again = sch.ScheduleStore(p).get(a["id"])
    assert again["last_run"] == "2026-11-16" and again["skip_date"] == "2026-11-17"                      # überlebt einen Neustart
    st.mark(a["id"], skip_date=None)
    assert "skip_date" not in sch.ScheduleStore(p).get(a["id"])
    assert st.replace(a["id"], raw(name="Neu"))["name"] == "Neu" and "last_run" not in st.get(a["id"])      # Änderung setzt den Zustand zurück
    assert st.replace("nix", raw()) is None and st.delete(a["id"]) is True and st.delete(a["id"]) is False
    for i in range(sch.MAX_SCHEDULES):
        st.create(raw(name=f"P{i}"))
    with pytest.raises(sch.ScheduleError):
        st.create(raw())
    p.write_text("{kaputt", encoding="utf-8")
    assert sch.ScheduleStore(p).list() == []
    p.write_text(json.dumps({"schedules": [raw(), {"name": "", "days": []}, "müll", raw(action={"type": "format"}), {**raw(), "last_run": "gestern"}]}), encoding="utf-8")
    items = sch.ScheduleStore(p).list()
    assert len(items) == 2 and all("last_run" not in i for i in items)
    assert not list(tmp_path.glob("*.tmp"))


def test_next_run_date():
    s = sch.clean_schedule(raw())                                                                         # Mo–Fr 07:30
    assert sch.next_run_date(s, MONDAY - timedelta(hours=1)) == MONDAY.date()                              # vor der Uhrzeit: heute
    assert sch.next_run_date(s, MONDAY + timedelta(seconds=60)) == MONDAY.date()                           # kurz nach der Uhrzeit zählt noch als heute (Toleranz)
    assert sch.next_run_date(s, MONDAY + timedelta(minutes=10)) == (MONDAY + timedelta(days=1)).date()
    friday_late = MONDAY + timedelta(days=4, hours=2)
    assert sch.next_run_date(s, friday_late) == (MONDAY + timedelta(days=7)).date()                        # Freitag nach der Zeit -> Montag
    assert sch.next_run_date(sch.clean_schedule(raw(days=[6])), MONDAY) == (MONDAY + timedelta(days=6)).date()


# ---------------------------------------------------------------- Ablauf
class FakeAudit:
    def __init__(self):
        self.rows = []

    def add(self, who, what, pc=None, detail=None, ok=True):
        self.rows.append((who, what, pc, detail, ok))

    def whats(self):
        return [r[1] for r in self.rows]


class FakeRunner:
    def __init__(self):
        self.started, self.ran, self.busy = [], [], False

    def start(self, hub, scene, who):
        if self.busy:
            raise sc.SceneError("Auf diesem PC läuft schon eine Szene")
        self.started.append((hub.pc_id, scene["name"], who))

    async def run(self, hub, scene, who):
        self.ran.append(scene["name"])


class Rig:
    def __init__(self, tmp_path, status="offline"):
        self.t = MONDAY - timedelta(minutes=5)
        self.hub = Hub({"agent_host": "127.0.0.1"}, "pc", "Gaming-PC")
        self.hub.status = status
        self.hubs = {"pc": self.hub}
        self.store = sch.ScheduleStore(tmp_path / "s.json")
        self.scenes = sc.SceneStore(tmp_path / "sc.json")
        self.runner, self.audit, self.woke, self.actions, self.spawned = FakeRunner(), FakeAudit(), [], [], []
        self.nomac = False

        async def act(name, body):
            self.actions.append(name)
            return 200, {"ok": True}

        self.hub.agent_action = act
        self.make()

    def make(self):
        def send_wake(hub):
            if self.nomac:
                raise HTTPException(status_code=400, detail="MAC-Adresse ist nicht konfiguriert")
            self.woke.append(hub.pc_id)

        self.sched = sch.Scheduler(self.store, self.hubs, self.scenes, self.runner, self.audit, send_wake, now=lambda: self.t, spawn=self.spawned.append)

    def tick(self, minutes=0, seconds=0):
        self.t += timedelta(minutes=minutes, seconds=seconds)
        asyncio.run(self.sched.tick())
        for coro in self.spawned:                                                                         # gestartete Szenen zu Ende laufen lassen
            asyncio.run(coro)
        self.spawned.clear()


def test_a_wake_schedule_fires_once_at_its_time_on_matching_days(tmp_path):
    r = Rig(tmp_path)
    r.store.create(raw())
    r.tick(minutes=4)
    assert r.woke == []                                                                                   # 07:29: noch nicht
    r.tick(minutes=1)
    assert r.woke == ["pc"] and r.audit.whats() == ["Zeitplan: PC aufgeweckt"]
    r.tick(seconds=20)
    r.tick(minutes=1)
    assert r.woke == ["pc"]                                                                               # nicht doppelt am selben Tag
    r2 = Rig(tmp_path / "x") if (tmp_path / "x").mkdir() is None else None
    r2.t = datetime(2026, 11, 21, 7, 29, tzinfo=TZ)                                                       # Samstag
    r2.store.create(raw())
    r2.tick(minutes=1)
    assert r2.woke == []                                                                                  # kein Werktag


def test_missed_runs_are_not_caught_up_and_disabled_plans_stay_silent(tmp_path):
    r = Rig(tmp_path)
    r.store.create(raw())
    r.t = MONDAY + timedelta(minutes=30)                                                                  # der Hub war bis 08:00 aus
    r.tick()
    assert r.woke == [] and r.audit.rows == []
    r2 = Rig(tmp_path / "d") if (tmp_path / "d").mkdir() is None else None
    r2.store.create(raw(enabled=False))
    r2.tick(minutes=5)
    assert r2.woke == []


def test_a_restart_within_the_same_minute_does_not_fire_twice(tmp_path):
    r = Rig(tmp_path)
    r.store.create(raw())
    r.tick(minutes=5)
    assert r.woke == ["pc"]
    r.make()                                                                                              # neuer Planer, derselbe Speicher (Neustart)
    r.tick(seconds=15)
    assert r.woke == ["pc"]


def test_skip_next_skips_exactly_one_run_and_can_be_undone(tmp_path):
    r = Rig(tmp_path)
    s = r.store.create(raw())
    assert r.sched.skip_next(s["id"]) == MONDAY.date().isoformat()                                        # heute 07:30 steht noch aus
    r.tick(minutes=5)
    assert r.woke == [] and r.audit.whats() == ["Zeitplan übersprungen"] and "skip_date" not in r.store.get(s["id"])
    r.t = MONDAY + timedelta(days=1, minutes=-5)
    r.tick(minutes=5)
    assert r.woke == ["pc"]                                                                               # am Dienstag läuft er wieder
    s2 = r.store.create(raw(name="Zwei"))
    r.sched.skip_next(s2["id"])
    r.sched.unskip(s2["id"])
    assert "skip_date" not in r.store.get(s2["id"]) and r.sched.skip_next("nix") is None


def test_wake_edge_cases_online_and_missing_mac(tmp_path):
    r = Rig(tmp_path, status="online")
    r.store.create(raw())
    r.tick(minutes=5)
    assert r.woke == [] and r.audit.whats() == ["Zeitplan: PC war schon online"]
    r2 = Rig(tmp_path / "m") if (tmp_path / "m").mkdir() is None else None
    r2.nomac = True
    r2.store.create(raw())
    r2.tick(minutes=5)
    assert r2.audit.rows[0][1] == "Zeitplan fehlgeschlagen" and "MAC" in r2.audit.rows[0][3] and r2.audit.rows[0][4] is False


def test_a_scene_schedule_starts_the_scene_on_the_scenes_pc(tmp_path):
    r = Rig(tmp_path)
    scene = r.scenes.create({"name": "Zocken", "steps": [{"type": "wait", "seconds": 1}]})
    r.store.create(raw(action={"type": "scene", "scene_id": scene["id"]}))
    r.tick(minutes=5)
    assert r.runner.started == [("pc", "Zocken", "Zeitplan")] and r.runner.ran == ["Zocken"]
    assert r.audit.whats() == ["Zeitplan: Szene gestartet"]


def test_scene_schedule_problems_are_reported(tmp_path):
    r = Rig(tmp_path)
    r.store.create(raw(action={"type": "scene", "scene_id": "weg-123"}))
    r.tick(minutes=5)
    assert r.audit.rows[0][1] == "Zeitplan fehlgeschlagen" and "existiert nicht" in r.audit.rows[0][3]
    r2 = Rig(tmp_path / "b") if (tmp_path / "b").mkdir() is None else None
    scene = r2.scenes.create({"name": "Z", "steps": [{"type": "wait", "seconds": 1}]})
    r2.runner.busy = True
    r2.store.create(raw(action={"type": "scene", "scene_id": scene["id"]}))
    r2.tick(minutes=5)
    assert r2.audit.rows[0][1] == "Zeitplan fehlgeschlagen" and "schon eine Szene" in r2.audit.rows[0][3] and r2.runner.ran == []


def idle_plan(r, **act):
    r.store.create(raw(time="22:00", days=list(range(7)), action={"type": "standby_if_idle", "idle_minutes": 10, "window_minutes": 60, **act}))
    r.t = MONDAY.replace(hour=21, minute=59)


def quiet(hub, gpu=3, cpu=5, jobs=(), steam=None):
    hub.snapshot = {"gpu": {"util_pct": gpu}, "cpu": {"util_pct": cpu}, "jobs": list(jobs), "steam": {"running": steam, "downloading": None}}


def test_standby_if_idle_waits_for_a_quiet_stretch_then_switches_off(tmp_path):
    r = Rig(tmp_path, status="online")
    idle_plan(r)
    quiet(r.hub)
    r.tick(minutes=1)
    assert r.audit.whats() == ["Zeitplan: wartet auf Ruhe"] and r.actions == []
    for _ in range(9):
        r.tick(minutes=1)
    assert r.actions == []                                                                                # erst 9 Minuten ruhig
    r.tick(minutes=1)
    assert r.actions == ["standby"] and r.audit.whats()[-1] == "Zeitplan: PC ausgeschaltet" and r.sched.watch == {}
    r.tick(minutes=5)
    assert r.actions == ["standby"]                                                                       # nur einmal


def test_activity_resets_the_quiet_timer_and_the_window_ends_the_wait(tmp_path):
    r = Rig(tmp_path, status="online")
    idle_plan(r)
    quiet(r.hub)
    r.tick(minutes=1)
    for _ in range(8):
        r.tick(minutes=1)
    quiet(r.hub, jobs=[{"state": "running"}])                                                            # ein Job startet: Zähler zurück
    r.tick(minutes=1)
    quiet(r.hub)
    for _ in range(9):
        r.tick(minutes=1)
    assert r.actions == []
    quiet(r.hub, gpu=80)
    for _ in range(45):
        r.tick(minutes=1)
    assert r.actions == [] and r.audit.whats()[-1] == "Zeitplan: übersprungen" and r.sched.watch == {}
    assert "beschäftigt" in r.audit.rows[-1][3]


@pytest.mark.parametrize("snap,idle", [
    (dict(gpu=14, cpu=39), True), (dict(gpu=15, cpu=5), False), (dict(gpu=1, cpu=40), False), (dict(gpu=1, cpu=1, steam={"appid": 730, "name": "CS2"}), False),
    (dict(gpu=1, cpu=1, jobs=[{"state": "queued"}]), False), (dict(gpu=1, cpu=1, jobs=[{"state": "done"}, {"state": "error"}]), True)])
def test_idle_definition(tmp_path, snap, idle):
    r = Rig(tmp_path, status="online")
    quiet(r.hub, **snap)
    assert sch.Scheduler.is_idle(r.hub) is idle
    r.hub.scene_run = {"state": "running"}
    assert sch.Scheduler.is_idle(r.hub) is False
    r.hub.snapshot = None
    r.hub.scene_run = None
    assert sch.Scheduler.is_idle(r.hub) is True                                                           # ohne Messwerte gilt der PC als ruhig, entschieden wird erst nach der Ruhezeit


def test_standby_if_idle_does_nothing_when_the_pc_is_already_off_and_uses_the_chosen_mode(tmp_path):
    r = Rig(tmp_path, status="offline")
    idle_plan(r)
    r.tick(minutes=1)
    r.tick(minutes=1)
    assert r.actions == [] and "PC ist schon aus" in r.audit.rows[-1][3]
    r2 = Rig(tmp_path / "m") if (tmp_path / "m").mkdir() is None else None
    r2.hub.status = "online"
    idle_plan(r2, mode="shutdown", idle_minutes=1)
    quiet(r2.hub)
    r2.tick(minutes=1)
    r2.tick(minutes=1)
    assert r2.actions == ["shutdown"]


# ---------------------------------------------------------------- Endpunkte
OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "t"}]}


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        yield c


def view_token(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    return client.post("/api/pair/redeem", json={"code": code}).json()["token"]


def test_schedule_endpoints_crud_validation_and_rights(client):
    assert client.get("/api/schedules").status_code == 401 and client.post("/api/schedules", json=raw()).status_code == 401
    v = {"Authorization": "Bearer " + view_token(client)}
    assert client.get("/api/schedules", headers=v).status_code == 200
    for method, path in (("POST", "/api/schedules"), ("PUT", "/api/schedules/x"), ("DELETE", "/api/schedules/x"), ("POST", "/api/schedules/x/skip"), ("DELETE", "/api/schedules/x/skip")):
        assert client.request(method, path, headers=v, json=raw()).status_code == 403, (method, path)
    made = client.post("/api/schedules", headers=MASTER, json=raw())
    assert made.status_code == 200 and made.json()["text"] == "Mo–Fr um 07:30: PC aufwecken" and made.json()["next"]
    sid = made.json()["id"]
    lst = client.get("/api/schedules", headers=MASTER).json()
    assert [s["id"] for s in lst["schedules"]] == [sid] and lst["timezone"] and lst["now"]
    assert client.post("/api/schedules", headers=MASTER, json=raw(time="99:99")).status_code == 400
    assert client.put(f"/api/schedules/{sid}", headers=MASTER, json=raw(name="Neu", enabled=False)).json()["next"] is None
    assert client.put("/api/schedules/nix", headers=MASTER, json=raw()).status_code == 404 and client.put(f"/api/schedules/{sid}", headers=MASTER, json={}).status_code == 400
    skip = client.post(f"/api/schedules/{sid}/skip", headers=MASTER)
    assert skip.status_code == 200 and len(skip.json()["skip_date"]) == 10
    assert client.get("/api/schedules", headers=MASTER).json()["schedules"][0]["skip_date"] == skip.json()["skip_date"]
    assert client.delete(f"/api/schedules/{sid}/skip", headers=MASTER).json() == {"ok": True}
    assert "skip_date" not in client.get("/api/schedules", headers=MASTER).json()["schedules"][0]
    assert client.delete(f"/api/schedules/{sid}", headers=MASTER).json() == {"ok": True} and client.delete(f"/api/schedules/{sid}", headers=MASTER).status_code == 404
    assert client.post("/api/schedules/..%2Fx/skip", headers=MASTER).status_code in (404, 405)
    raw_audit = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    for t in ("Zeitplan angelegt", "Zeitplan geändert", "Zeitplan gelöscht", "nächsten Lauf überspringen"):
        assert t in raw_audit


def test_schedules_that_switch_the_pc_off_need_the_pin_when_one_is_set(tmp_path):
    opts = json.loads(json.dumps(OPTS))
    opts["confirm_pin"] = "4711"
    with TestClient(create_app(opts, data_dir=tmp_path)) as c:
        idle = raw(action={"type": "standby_if_idle"})
        assert c.post("/api/schedules", headers=MASTER, json=idle).status_code == 428
        assert c.post("/api/schedules", headers={**MASTER, "X-Confirm-PIN": "0000"}, json=idle).status_code == 403
        made = c.post("/api/schedules", headers={**MASTER, "X-Confirm-PIN": "4711"}, json=idle)
        assert made.status_code == 200
        sid = made.json()["id"]
        assert c.put(f"/api/schedules/{sid}", headers=MASTER, json=raw()).status_code == 428                   # auch das Entschärfen braucht die PIN
        assert c.post("/api/schedules", headers=MASTER, json=raw()).status_code == 200                           # Aufwecken braucht keine
        assert c.post("/api/schedules", headers=MASTER, json=raw(time="99:99")).status_code == 400              # Eingabefehler vor der PIN-Abfrage nicht verwechselt


def test_the_hub_runs_the_scheduler_in_the_background(tmp_path):
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        assert c.get("/api/schedules", headers=MASTER).json()["timezone"] != ""
        assert c.app.router.lifespan_context is not None
