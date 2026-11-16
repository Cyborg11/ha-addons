"""Sicherheits-PIN (Phase 10.4): kritische Aktionen verlangen confirm_pin, serverseitig geprüft; App-Verknüpfungen im Manifest."""
import json
import os
import time
from pathlib import Path

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import scenes as sc
from app.main import create_app

MASTER = {"Authorization": "Bearer master"}
PIN = {"X-Confirm-PIN": "4711"}
CRITICAL = [("POST", "/api/action/shutdown"), ("POST", "/api/action/restart"), ("POST", "/api/action/sleep"), ("POST", "/api/action/standby"),
            ("POST", "/api/processes/12/kill"), ("POST", "/api/programs/comfy/stop"), ("POST", "/api/steam/games/730/stop")]
HARMLESS = [("POST", "/api/action/lock"), ("POST", "/api/action/mute"), ("POST", "/api/action/monitor_off"), ("POST", "/api/programs/comfy/start"),
            ("POST", "/api/job/j1/cancel"), ("POST", "/api/steam/games/730/launch"), ("POST", "/api/wake")]


def make_client(tmp_path, pin):
    opts = {"ui_token": "master", "pcs": [{"name": "PC", "host": "10.0.0.5", "token": "t", "mac": "AA:BB:CC:DD:EE:FF"}]}
    if pin is not None:
        opts["confirm_pin"] = pin
    return TestClient(create_app(opts, data_dir=tmp_path))


@pytest.fixture()
def calls():
    return []


def arm(c, calls):
    for h in c.app.state.hubs.values():
        h.status = "online"

        async def fake(method, path, params=None, body=None, timeout=15.0):
            calls.append((method, path))
            return 200, json.dumps({"ok": True}).encode(), "application/json"

        async def act(name, body):
            calls.append(("ACTION", name))
            return 200, {"ok": True}

        async def fetch(method, path, params=None, body=None, timeout=15.0, extra_headers=None):
            code, content, ctype = await fake(method, path, params, body, timeout)
            return code, content, ctype, {}

        h.agent_request, h.agent_action, h.agent_fetch = fake, act, fetch


@pytest.fixture()
def client(tmp_path, calls, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "send_magic_packet", lambda mac, ip: None)
    with make_client(tmp_path, "4711") as c:
        arm(c, calls)
        yield c


def test_without_the_option_nothing_changes(tmp_path, calls, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "send_magic_packet", lambda mac, ip: None)
    with make_client(tmp_path, None) as c:
        arm(c, calls)
        for method, path in CRITICAL:
            assert c.request(method, path, headers=MASTER).status_code == 200, path
    with make_client(tmp_path, "") as c:                                                                   # leere Option = aus
        arm(c, calls)
        assert c.post("/api/action/shutdown", headers=MASTER).status_code == 200


def test_critical_actions_need_the_pin_before_anything_reaches_the_agent(client, calls):
    for method, path in CRITICAL:
        r = client.request(method, path, headers=MASTER)
        assert r.status_code == 428 and r.json()["detail"] == "PIN erforderlich", path
    assert calls == []                                                                                     # nichts erreichte den Agenten
    for method, path in CRITICAL:
        assert client.request(method, path, headers={**MASTER, **PIN}).status_code == 200, path
    assert len(calls) >= len(CRITICAL)


def test_harmless_actions_never_ask_for_the_pin(client):
    for method, path in HARMLESS:
        assert client.request(method, path, headers=MASTER).status_code == 200, path


def test_wrong_pins_are_refused_logged_and_lock_after_five_attempts(client, calls):
    bad = {**MASTER, "X-Confirm-PIN": "0000"}
    for i in range(5):
        r = client.post("/api/action/shutdown", headers=bad)
        assert r.status_code == 403 and r.json()["detail"] == "PIN falsch", i
    r = client.post("/api/action/shutdown", headers=bad)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert client.post("/api/action/shutdown", headers={**MASTER, **PIN}).status_code == 429               # gesperrt gilt auch für die richtige PIN
    assert client.post("/api/processes/12/kill", headers={**MASTER, **PIN}).status_code == 429             # und für alle kritischen Aktionen
    assert calls == []
    assert client.post("/api/action/lock", headers=MASTER).status_code == 200                              # Harmloses bleibt möglich
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert raw.count("Falsche Sicherheits-PIN") == 5 and "4711" not in raw and "0000" not in raw


def test_the_pin_must_match_exactly(client):
    for given in ("4711 ", " 4711", "47110", "471"):                                                        # unter der Sperrgrenze von 5 bleiben
        assert client.post("/api/action/shutdown", headers={**MASTER, "X-Confirm-PIN": given}).status_code == 403, repr(given)
    assert client.post("/api/action/shutdown", headers={**MASTER, **PIN}).status_code == 200                # die richtige PIN geht


def test_other_checks_come_before_the_pin(client, calls):
    assert client.post("/api/action/shutdown").status_code == 401                                          # ohne Anmeldung: 401, nicht 428
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    v = {"Authorization": "Bearer " + client.post("/api/pair/redeem", json={"code": code}).json()["token"]}
    assert client.post("/api/action/shutdown", headers={**v, **PIN}).status_code == 403                    # Nur-Ansicht: 403 wegen Rolle
    assert client.post("/api/action/shutdown", headers=v).status_code == 403                               # ohne PIN-Aufforderung
    assert client.post("/api/action/format_c", headers=MASTER).status_code == 404                          # unbekannte Aktion
    assert calls == []


def test_scenes_with_critical_steps_need_the_pin_others_do_not(client, calls):
    safe = client.post("/api/scenes", headers=MASTER, json={"name": "Sicher", "steps": [{"type": "action", "name": "mute"}, {"type": "wait", "seconds": 1}]}).json()["id"]
    risky = client.post("/api/scenes", headers=MASTER, json={"name": "Aus", "steps": [{"type": "action", "name": "shutdown"}]}).json()["id"]
    assert client.post(f"/api/scenes/{risky}/run", headers=MASTER).status_code == 428
    assert client.post(f"/api/scenes/{safe}/run", headers=MASTER).status_code == 202
    time.sleep(1.5)
    client.post("/api/scenes/cancel", headers=MASTER)
    assert client.post(f"/api/scenes/{risky}/run", headers={**MASTER, **PIN}).status_code in (202, 409)     # mit PIN erlaubt (409 nur, falls die andere Szene noch läuft)


def test_scene_criticality_rules():
    def scene(*steps):
        return sc.clean_scene({"name": "S", "steps": list(steps)})
    assert sc.is_critical(scene({"type": "action", "name": "standby"})) and sc.is_critical(scene({"type": "action", "name": "restart"}))
    assert sc.is_critical(scene({"type": "program_stop", "id": "x"})) and sc.is_critical(scene({"type": "game_stop", "appid": 5}))
    assert sc.is_critical(scene({"type": "power_plan", "after_job": "shutdown"})) and sc.is_critical(scene({"type": "wait", "seconds": 1}, {"type": "action", "name": "sleep"}))
    for harmless in ({"type": "action", "name": "mute"}, {"type": "action", "name": "lock"}, {"type": "wait", "seconds": 3}, {"type": "program_start", "id": "x"},
                     {"type": "game_launch", "appid": 5}, {"type": "ha_scene", "entity_id": "scene.a"}, {"type": "notify", "message": "x"}, {"type": "power_plan", "cancel": True},
                     {"type": "action", "name": "volume", "level": 5}):
        assert not sc.is_critical(scene(harmless)), harmless


def test_manifest_shortcuts_use_only_known_deep_links():
    m = json.loads((Path(__file__).parent.parent / "app" / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
    urls = [s["url"] for s in m["shortcuts"]]
    assert urls == ["./#do=wake", "./#do=standby", "./#do=tab:steam"] and len(m["shortcuts"]) <= 4         # Android zeigt höchstens 4
    assert all(s["name"] and s["short_name"] and s["icons"] for s in m["shortcuts"]) and m["start_url"] == "./"
