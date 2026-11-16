"""Szenen (Phase 10.2): Prüfung der Eingaben, Speicher, Ablauf mit gefälschter Uhr, Aufwecken, Abbruch, Endpunkte und Rechte."""
import asyncio
import json
import os
import time

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main as main_mod
from app import scenes as sc
from app.hub import Hub
from app.main import create_app

MASTER = {"Authorization": "Bearer master"}


# ---------------------------------------------------------------- Prüfung
def good_steps():
    return [{"type": "program_stop", "id": "comfyui", "name": "ComfyUI"}, {"type": "game_launch", "appid": 730, "name": "Counter-Strike 2"},
            {"type": "action", "name": "volume", "level": 30}, {"type": "power_plan", "after_job": "standby"},
            {"type": "ha_scene", "entity_id": "scene.zocken"}, {"type": "wait", "seconds": 5}, {"type": "notify", "message": "los"}]


def test_a_valid_scene_is_cleaned_and_gets_an_id():
    s = sc.clean_scene({"name": "  Zocken ", "icon": "🎮", "steps": good_steps()})
    assert s["name"] == "Zocken" and s["icon"] == "🎮" and s["wake"] is True and len(s["steps"]) == 7 and s["id"].startswith("zocken-")
    assert [st["type"] for st in s["steps"]] == [x["type"] for x in good_steps()]


@pytest.mark.parametrize("step", [
    {"type": "format_c"}, {"type": "program_start", "id": "../x"}, {"type": "program_start", "id": ""}, {"type": "game_launch", "appid": 0},
    {"type": "game_launch", "appid": 2 ** 32}, {"type": "game_stop", "appid": "730"}, {"type": "game_stop", "appid": True},
    {"type": "action", "name": "restart_agent"}, {"type": "action", "name": "clipboard_set"}, {"type": "action", "name": "open_url"},
    {"type": "action", "name": "volume", "level": 101}, {"type": "action", "name": "volume"}, {"type": "power_plan"},
    {"type": "power_plan", "after_job": "hibernate"}, {"type": "power_plan", "timer_minutes": 0}, {"type": "power_plan", "timer_minutes": 5, "mode": "x"},
    {"type": "ha_scene", "entity_id": "light.wohnzimmer"}, {"type": "ha_scene", "entity_id": "scene.Gross"}, {"type": "ha_scene", "entity_id": "scene.a b"},
    {"type": "wait", "seconds": 0}, {"type": "wait", "seconds": 301}, {"type": "wait", "seconds": 1.5}, {"type": "notify", "message": ""}, {"type": "notify"},
    "kein dict", None, {},
])
def test_invalid_steps_are_rejected(step):
    with pytest.raises(sc.SceneError):
        sc.clean_step(step)


def test_unknown_fields_never_survive_and_text_is_sanitised():
    st = sc.clean_step({"type": "program_start", "id": "comfy", "name": "Co\nmfy" + "x" * 200, "cmd": "calc.exe", "args": ["--evil"]})
    assert set(st) == {"type", "id", "name"} and "\n" not in st["name"] and len(st["name"]) <= 60
    assert sc.clean_step({"type": "game_launch", "appid": 5, "force": "ja"}) == {"type": "game_launch", "appid": 5, "name": ""}      # nur echtes True zählt
    assert sc.clean_step({"type": "game_launch", "appid": 5, "force": True})["force"] is True


def test_scene_level_limits():
    ok = {"name": "A", "steps": [{"type": "wait", "seconds": 1}]}
    for bad in ({**ok, "name": ""}, {**ok, "name": "x" * 5}, {**ok, "steps": []}, {**ok, "steps": "x"}, {**ok, "steps": [{"type": "wait", "seconds": 1}] * 31},
                {**ok, "pc": "../x"}, "text", None):
        if bad is not None and isinstance(bad, dict) and bad.get("name") == "x" * 5:
            continue                                                                                   # 5 Zeichen sind erlaubt (Limit ist 40)
        with pytest.raises(sc.SceneError):
            sc.clean_scene(bad)
    assert len(sc.clean_scene({**ok, "name": "n" * 100})["name"]) == 40
    assert sc.clean_scene({**ok, "wake": False})["wake"] is False and sc.clean_scene({**ok, "pc": "gaming-pc"})["pc"] == "gaming-pc"


# ---------------------------------------------------------------- Speicher
def test_store_persists_limits_and_survives_garbage(tmp_path):
    p = tmp_path / "scenes.json"
    st = sc.SceneStore(p)
    a = st.create({"name": "Eins", "steps": [{"type": "wait", "seconds": 2}]})
    b = st.create({"name": "Zwei", "steps": [{"type": "action", "name": "lock"}]})
    assert [s["name"] for s in sc.SceneStore(p).list()] == ["Eins", "Zwei"]                              # überlebt einen Neustart
    assert st.replace(a["id"], {"name": "Eins neu", "steps": [{"type": "wait", "seconds": 3}]})["id"] == a["id"] and st.replace("nix", {"name": "x", "steps": [{"type": "wait", "seconds": 1}]}) is None
    st.move([b["id"], a["id"]])
    assert [s["name"] for s in sc.SceneStore(p).list()] == ["Zwei", "Eins neu"]
    assert st.delete(a["id"]) is True and st.delete(a["id"]) is False
    for i in range(sc.MAX_SCENES - 1):
        st.create({"name": f"S{i}", "steps": [{"type": "wait", "seconds": 1}]})
    with pytest.raises(sc.SceneError):
        st.create({"name": "zu viel", "steps": [{"type": "wait", "seconds": 1}]})
    p.write_text("{kaputt", encoding="utf-8")
    assert sc.SceneStore(p).list() == []
    p.write_text(json.dumps({"scenes": [{"name": "gut", "steps": [{"type": "wait", "seconds": 1}]}, {"name": "", "steps": []}, "müll", {"name": "böse", "steps": [{"type": "action", "name": "format"}]}]}), encoding="utf-8")
    assert [s["name"] for s in sc.SceneStore(p).list()] == ["gut"]                                       # kaputte Einträge werden übersprungen
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------- Ablauf
class FakeAudit:
    def __init__(self):
        self.rows = []

    def add(self, who, what, pc=None, detail=None, ok=True):
        self.rows.append((who, what, pc, detail, ok))


class FakeHA:
    def __init__(self):
        self.scenes, self.sent, self.fail = [], [], None

    async def activate_scene(self, entity):
        self.scenes.append(entity)
        return (False, "HA kaputt") if self.fail else (True, "")

    async def send(self, title, message, tag=None):
        self.sent.append(message)
        return True, "gesendet"


class Rig:
    def __init__(self, status="online"):
        self.t = 1000.0
        self.hub = Hub({"agent_host": "127.0.0.1", "wake_mode": "standby"}, "pc", "Gaming-PC")
        self.hub.status, self.hub.features = status, ["steam"]
        self.calls, self.actions, self.audit, self.ha, self.woke, self.answers = [], [], FakeAudit(), FakeHA(), [], {}
        self.on_sleep = None
        self.updates = []

        async def request(method, path, params=None, body=None, timeout=15.0):
            self.calls.append((method, path, body))
            code, data = self.answers.get((method, path), (200, {"ok": True}))
            return code, json.dumps(data).encode(), "application/json"

        async def action(name, body):
            self.actions.append((name, body))
            code, data = self.answers.get(("ACTION", name), (200, {"ok": True}))
            return code, data

        async def broadcast():
            if self.hub.scene_run:
                self.updates.append(json.loads(json.dumps(self.hub.scene_run["steps"])))

        self.hub.agent_request, self.hub.agent_action, self.hub.broadcast = request, action, broadcast
        self.hub._now = lambda: self.t

        def send_wake(hub):
            self.woke.append(self.t)
            if self.answers.get("nomac"):
                raise HTTPException(status_code=400, detail="MAC-Adresse ist nicht konfiguriert")

        async def sleep(s):
            self.t += s
            if self.on_sleep:
                self.on_sleep(self)

        self.runner = sc.SceneRunner(self.ha, self.audit, send_wake, sleep=sleep, clock=lambda: self.t)

    def run(self, scene_raw):
        scene = sc.clean_scene(scene_raw)
        self.runner.start(self.hub, scene, "Test")
        asyncio.run(self.runner.run(self.hub, scene, "Test"))
        return self.hub.scene_run

    def states(self):
        return [s["state"] for s in self.hub.scene_run["steps"]]


def test_a_scene_runs_its_steps_in_order_with_the_right_agent_calls():
    rig = Rig()
    run = rig.run({"name": "Zocken", "steps": good_steps() + [{"type": "game_stop", "appid": 440}, {"type": "program_start", "id": "x"}]})
    assert run["state"] == "ok" and rig.states() == ["ok"] * 9 and run["error"] is None
    assert rig.calls == [("POST", "/api/programs/comfyui/stop", None), ("POST", "/api/steam/games/730/launch", {"force": False}),
                         ("POST", "/api/power-plan", {"after_job": "standby"}), ("POST", "/api/steam/games/440/stop", None), ("POST", "/api/programs/x/start", None)]
    assert rig.actions == [("volume", {"level": 30})] and rig.ha.scenes == ["scene.zocken"] and rig.ha.sent == ["los"]
    assert rig.t - 1000.0 >= 5                                                                          # die Wartezeit wurde wirklich abgewartet
    assert [r[1] for r in rig.audit.rows] == ["Szene gestartet", "Szene beendet"]
    assert any(u[0]["state"] == "running" for u in rig.updates) and len(rig.updates) >= 9               # jeder Schritt wurde an die Oberfläche gemeldet


def test_a_failing_step_stops_the_scene_and_marks_the_rest_skipped():
    rig = Rig()
    rig.answers[("POST", "/api/steam/games/730/launch")] = (409, {"detail": "Es läuft bereits ein anderes Spiel: X"})
    run = rig.run({"name": "Zocken", "steps": good_steps()})
    assert run["state"] == "error" and rig.states() == ["ok", "error"] + ["skipped"] * 5
    assert "Schritt 2" in run["error"] and "anderes Spiel" in run["error"]
    assert rig.actions == [] and rig.ha.scenes == []                                                    # nichts nach dem Fehler
    assert rig.audit.rows[-1][1] == "Szene fehlgeschlagen" and rig.audit.rows[-1][4] is False


def test_stopping_a_game_that_is_not_running_is_not_an_error():
    rig = Rig()
    rig.answers[("POST", "/api/steam/games/440/stop")] = (409, {"detail": "Spielprozess nicht gefunden"})
    assert rig.run({"name": "S", "steps": [{"type": "game_stop", "appid": 440}, {"type": "action", "name": "lock"}]})["state"] == "ok"
    rig2 = Rig()
    rig2.answers[("POST", "/api/steam/games/440/stop")] = (502, {"detail": "Agent weg"})
    assert rig2.run({"name": "S", "steps": [{"type": "game_stop", "appid": 440}]})["state"] == "error"


def test_ha_and_action_errors_are_reported_with_their_text():
    rig = Rig()
    rig.ha.fail = True
    run = rig.run({"name": "S", "steps": [{"type": "ha_scene", "entity_id": "scene.x"}]})
    assert run["state"] == "error" and "HA kaputt" in run["error"]
    rig = Rig()
    rig.answers[("ACTION", "lock")] = (501, {"detail": "nur unter Windows"})
    assert "nur unter Windows" in rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})["error"]


def test_power_plan_steps_use_post_and_delete():
    rig = Rig()
    rig.run({"name": "S", "steps": [{"type": "power_plan", "timer_minutes": 30, "mode": "sleep"}, {"type": "power_plan", "cancel": True}]})
    assert rig.calls == [("POST", "/api/power-plan", {"timer_minutes": 30, "mode": "sleep"}), ("DELETE", "/api/power-plan?which=all", None)]


def test_cancel_stops_between_steps_and_during_a_wait():
    rig = Rig()
    rig.on_sleep = lambda r: r.hub.scene_run.update(cancel=True)
    run = rig.run({"name": "S", "steps": [{"type": "wait", "seconds": 60}, {"type": "action", "name": "lock"}]})
    assert run["state"] == "cancelled" and rig.actions == [] and rig.t - 1000.0 < 5 and rig.states() == ["skipped", "skipped"]
    rig = Rig()
    scene = sc.clean_scene({"name": "S", "steps": [{"type": "action", "name": "mute"}, {"type": "action", "name": "lock"}]})
    rig.runner.start(rig.hub, scene, "T")
    assert asyncio.run(rig.runner.cancel(rig.hub)) is True and asyncio.run(rig.runner.cancel(Rig().hub)) is False
    asyncio.run(rig.runner.run(rig.hub, scene, "T"))
    assert rig.hub.scene_run["state"] == "cancelled" and rig.actions == []


def test_only_one_scene_runs_per_pc():
    rig = Rig()
    scene = sc.clean_scene({"name": "S", "steps": [{"type": "wait", "seconds": 1}]})
    rig.runner.start(rig.hub, scene, "T")
    with pytest.raises(sc.SceneError):
        rig.runner.start(rig.hub, scene, "T")
    asyncio.run(rig.runner.run(rig.hub, scene, "T"))
    rig.runner.start(rig.hub, scene, "T")                                                               # danach wieder möglich


def test_offline_pc_is_woken_and_the_scene_waits_for_agent_and_steam():
    rig = Rig(status="offline")
    rig.hub.features = []
    state = {"n": 0}

    def tick(r):
        state["n"] += 1
        if state["n"] == 3:
            r.hub.status = "online"
        if state["n"] == 5:
            r.hub.features = ["steam"]                                                                  # Steam meldet sich erst später
    rig.on_sleep = tick
    run = rig.run({"name": "Zocken", "steps": [{"type": "game_launch", "appid": 730, "name": "CS2"}]})
    assert run["state"] == "ok" and len(rig.woke) == 1 and [s["label"] for s in run["steps"]] == ["PC aufwecken", "Spiel starten: CS2"]
    assert rig.states() == ["ok", "ok"] and rig.calls == [("POST", "/api/steam/games/730/launch", {"force": False})]
    assert state["n"] >= 3 + rig.hub.launch_delay                                                       # erst nach der Pause ab „online“ (und erst, als Steam sich meldete)


def test_a_waking_pc_is_not_woken_twice_and_no_wake_option_fails_fast():
    rig = Rig(status="waking")
    rig.on_sleep = lambda r: setattr(r.hub, "status", "online")
    assert rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})["state"] == "ok" and rig.woke == []
    rig = Rig(status="offline")
    run = rig.run({"name": "S", "wake": False, "steps": [{"type": "action", "name": "lock"}]})
    assert run["state"] == "error" and "nicht online" in run["error"] and rig.woke == [] and rig.actions == []


def test_wake_problems_are_reported_without_a_crash():
    rig = Rig(status="offline")
    rig.answers["nomac"] = True
    run = rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})
    assert run["state"] == "error" and "MAC" in run["error"] and rig.states() == ["error", "skipped"]
    rig = Rig(status="offline")                                                                         # PC meldet sich nie
    run = rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})
    assert run["state"] == "error" and "rechtzeitig" in run["error"] and rig.actions == []
    assert rig.t - 1000.0 <= rig.hub.launch_expiry + 2
    rig = Rig(status="offline")                                                                         # Abbruch beim Warten
    rig.on_sleep = lambda r: r.hub.scene_run.update(cancel=True)
    assert rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})["state"] == "cancelled"


def test_scene_run_is_part_of_the_hub_status_for_five_minutes():
    rig = Rig()
    rig.run({"name": "S", "steps": [{"type": "action", "name": "lock"}]})
    pub = rig.hub.message()["scene_run"]
    assert pub["state"] == "ok" and pub["name"] == "S" and "cancel" not in pub and pub["steps"][0]["label"] == "Aktion: lock"
    rig.t += 301
    assert rig.hub.message()["scene_run"] is None


# ---------------------------------------------------------------- Endpunkte
OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "t", "mac": "AA:BB:CC:DD:EE:FF"}, {"name": "KI-PC", "host": "10.0.0.6", "token": "t2"}]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main_mod, "send_magic_packet", lambda mac, ip: calls.append(("wol", mac)))
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        for pid, h in c.app.state.hubs.items():
            h.status = "online"

            async def fake(method, path, params=None, body=None, timeout=15.0, pid=pid):
                calls.append((pid, method, path, body))
                return 200, json.dumps({"ok": True}).encode(), "application/json"

            async def act(name, body, pid=pid):
                calls.append((pid, "ACTION", name, body))
                return 200, {"ok": True}

            h.agent_request, h.agent_action = fake, act
        c.calls = calls
        yield c


def view_token(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    return client.post("/api/pair/redeem", json={"code": code}).json()["token"]


def wait_done(client, pc=None, tries=60):
    for _ in range(tries):
        run = client.get("/api/status" + (f"?pc={pc}" if pc else ""), headers=MASTER).json()["scene_run"]
        if run and run["state"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("Szene wurde nicht fertig")


NEW = {"name": "Zocken", "icon": "🎮", "steps": [{"type": "program_stop", "id": "comfyui", "name": "ComfyUI"}, {"type": "action", "name": "mute"}]}


def test_scene_crud_validation_and_rights(client):
    assert client.get("/api/scenes").status_code == 401 and client.post("/api/scenes", json=NEW).status_code == 401
    v = {"Authorization": "Bearer " + view_token(client)}
    assert client.get("/api/scenes", headers=v).status_code == 200                                        # ansehen darf jeder angemeldete
    for method, path in (("POST", "/api/scenes"), ("PUT", "/api/scenes/x"), ("DELETE", "/api/scenes/x"), ("POST", "/api/scenes/x/run"), ("POST", "/api/scenes/cancel")):
        assert client.request(method, path, headers=v, json=NEW).status_code == 403, (method, path)
    made = client.post("/api/scenes", headers=MASTER, json=NEW)
    assert made.status_code == 200 and made.json()["name"] == "Zocken"
    sid = made.json()["id"]
    lst = client.get("/api/scenes", headers=MASTER).json()
    assert [s["id"] for s in lst["scenes"]] == [sid] and "volume" in lst["limits"]["actions"] and "restart_agent" not in lst["limits"]["actions"]
    assert client.post("/api/scenes", headers=MASTER, json={"name": "x", "steps": [{"type": "action", "name": "format_c"}]}).status_code == 400
    assert client.post("/api/scenes", headers=MASTER, json={"name": "", "steps": []}).status_code == 400
    assert client.put(f"/api/scenes/{sid}", headers=MASTER, json={**NEW, "name": "Neu"}).json()["name"] == "Neu"
    assert client.put("/api/scenes/nix", headers=MASTER, json=NEW).status_code == 404 and client.put(f"/api/scenes/{sid}", headers=MASTER, json={"name": ""}).status_code == 400
    assert client.delete(f"/api/scenes/{sid}", headers=MASTER).json() == {"ok": True} and client.delete(f"/api/scenes/{sid}", headers=MASTER).status_code == 404
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    for t in ("Szene angelegt", "Szene geändert", "Szene gelöscht"):
        assert t in raw


def test_run_executes_on_the_selected_pc_and_is_logged(client):
    sid = client.post("/api/scenes", headers=MASTER, json=NEW).json()["id"]
    assert client.post("/api/scenes/..%2Fx/run", headers=MASTER).status_code in (404, 405)
    r = client.post(f"/api/scenes/{sid}/run?pc=ki-pc", headers=MASTER)
    assert r.status_code == 202 and r.json()["pc"] == "ki-pc"
    run = wait_done(client, "ki-pc")
    assert run["state"] == "ok" and [s["state"] for s in run["steps"]] == ["ok", "ok"]
    assert [c for c in client.calls if c[0] == "ki-pc"] == [("ki-pc", "POST", "/api/programs/comfyui/stop", None), ("ki-pc", "ACTION", "mute", None)]
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert "Szene gestartet" in raw and "Szene beendet" in raw and "Zocken" in raw


def test_a_scene_bound_to_a_pc_runs_there_whatever_is_selected(client):
    sid = client.post("/api/scenes", headers=MASTER, json={**NEW, "pc": "ki-pc"}).json()["id"]
    assert client.post(f"/api/scenes/{sid}/run", headers=MASTER).json()["pc"] == "ki-pc"                  # ohne ?pc= würde sonst Gaming-PC gelten
    wait_done(client, "ki-pc")
    assert all(c[0] == "ki-pc" for c in client.calls)
    sid2 = client.post("/api/scenes", headers=MASTER, json={**NEW, "pc": "gibt-es-nicht"}).json()["id"]
    assert client.post(f"/api/scenes/{sid2}/run", headers=MASTER).status_code == 409


def test_run_from_an_offline_pc_sends_the_magic_packet(client):
    h = client.app.state.hubs["gaming-pc"]
    h.status = "offline"
    sid = client.post("/api/scenes", headers=MASTER, json={"name": "Aus", "steps": [{"type": "wait", "seconds": 1}]}).json()["id"]
    assert client.post(f"/api/scenes/{sid}/run", headers=MASTER).status_code == 202
    for _ in range(30):
        if ("wol", "AA:BB:CC:DD:EE:FF") in client.calls:
            break
        time.sleep(0.1)
    assert ("wol", "AA:BB:CC:DD:EE:FF") in client.calls
    assert client.post("/api/scenes/cancel", headers=MASTER).json() == {"ok": True, "cancelled": True}
    assert wait_done(client)["state"] == "cancelled"


def test_second_run_while_one_is_active_is_refused_and_cancel_without_run_is_harmless(client):
    assert client.post("/api/scenes/cancel", headers=MASTER).json() == {"ok": True, "cancelled": False}
    sid = client.post("/api/scenes", headers=MASTER, json={"name": "Lang", "steps": [{"type": "wait", "seconds": 60}]}).json()["id"]
    assert client.post(f"/api/scenes/{sid}/run", headers=MASTER).status_code == 202
    assert client.post(f"/api/scenes/{sid}/run", headers=MASTER).status_code == 409
    client.post("/api/scenes/cancel", headers=MASTER)
    assert wait_done(client)["state"] == "cancelled"


def test_ha_activation_only_touches_scene_turn_on():
    from app.notify import HaNotifier
    import httpx
    seen = []

    def handler(req):
        seen.append((req.method, str(req.url), json.loads(req.content)))
        return httpx.Response(200, json=[])

    ha = HaNotifier("notify.x", "tok", "http://ha/api", transport=httpx.MockTransport(handler))
    assert asyncio.run(ha.activate_scene("scene.zocken")) == (True, "")
    assert seen == [("POST", "http://ha/api/services/scene/turn_on", {"entity_id": "scene.zocken"})]
    for bad in ("light.x", "scene.", "scene.A", "../x", "scene.a/../b", ""):
        assert asyncio.run(ha.activate_scene(bad))[0] is False
    assert len(seen) == 1
    assert asyncio.run(HaNotifier("", None).activate_scene("scene.x"))[0] is False                       # ohne Token nichts senden


def test_display_profile_step_needs_a_valid_mode():
    assert sc.clean_step({"type": "action", "name": "display", "mode": "external"}) == {"type": "action", "name": "display", "mode": "external"}
    for bad in ({"type": "action", "name": "display"}, {"type": "action", "name": "display", "mode": "mirror"}):
        with pytest.raises(sc.SceneError):
            sc.clean_step(bad)
