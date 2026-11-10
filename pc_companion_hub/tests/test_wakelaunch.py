"""Aufwecken und starten (Phase 9.3): Wake-Modi, Zustandsmaschine mit gefälschter Uhr, Endpunkte und Rechte."""
import asyncio
import json
import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import hub as hub_mod
from app import main as main_mod
from app.hub import Hub, compute_status, wake_params
from app.main import build_pcs, create_app

MASTER = {"Authorization": "Bearer master"}


# ---------------------------------------------------------------- Optionen
def test_wake_params_defaults_modes_and_overrides():
    assert wake_params({}) == ("standby", 120, 5)
    assert wake_params({"wake_mode": "cold"}) == ("cold", 300, 25)
    assert wake_params({"wake_mode": "unfug"}) == ("standby", 120, 5)
    assert wake_params({"wake_mode": "cold", "wake_timeout_s": 600, "launch_delay_s": 0}) == ("cold", 600, 0)
    assert wake_params({"wake_timeout_s": 5, "launch_delay_s": 999}) == ("standby", 120, 5)           # außerhalb der Grenzen: Standard
    assert wake_params({"wake_timeout_s": True, "launch_delay_s": "20"}) == ("standby", 120, 5)       # falsche Typen werden ignoriert


def test_waking_status_uses_the_configured_timeout():
    assert compute_status(False, 100.0, 250.0) == "offline"                                           # Standard 120 s
    assert compute_status(False, 100.0, 250.0, 300) == "waking"
    assert compute_status(True, 100.0, 9999.0, 300) == "online"


def test_per_pc_options_override_the_global_ones():
    opts = {"wake_mode": "standby", "launch_delay_s": 7,
            "pcs": [{"name": "Gaming", "host": "10.0.0.5", "token": "t"},
                    {"name": "Server", "host": "10.0.0.6", "token": "t", "wake_mode": "cold", "wake_timeout_s": 400}]}
    (_, _, a), (_, _, b) = build_pcs(opts)
    assert wake_params(a) == ("standby", 120, 7) and wake_params(b) == ("cold", 400, 7)
    assert Hub(b, "server").message()["waking_total"] == 400 and Hub(b, "server").message()["wake_mode"] == "cold"


# ---------------------------------------------------------------- Zustandsmaschine
class Clock:
    t = 1000.0


@pytest.fixture()
def rig():
    clock = Clock()
    clock.t = 1000.0
    h = Hub({"agent_host": "127.0.0.1", "wake_mode": "standby"}, "pc")
    h._now = lambda: clock.t
    calls, results, answers = [], [], []

    async def fake_request(method, path, params=None, body=None, timeout=15.0):
        calls.append((method, path, body))
        code, data = answers.pop(0) if answers else (200, {"ok": True})
        return code, json.dumps(data).encode(), "application/json"

    h.agent_request = fake_request
    h.on_launch = lambda hub_, r: results.append(r)
    h.status, h.features = "offline", []
    return clock, h, calls, results, answers


def tick(h):
    asyncio.run(h._launch_tick())


def test_launch_waits_for_online_steam_and_delay_then_starts_once(rig):
    clock, h, calls, results, _ = rig
    h.queue_launch(730, "Counter-Strike 2")
    assert h.message()["pending_launch"] == {"appid": 730, "name": "Counter-Strike 2", "left_s": 240}   # Wartezeit 120 + Nachlauf 120
    tick(h)
    assert calls == []                                                                                  # PC noch aus
    h.status, h.features = "online", ["power_plan"]                                                     # online, aber (noch) kein Steam gemeldet
    clock.t += 30
    tick(h)
    assert calls == [] and h.pending_launch["online_since"] is None
    h.features = ["power_plan", "steam"]
    tick(h)
    assert calls == []                                                                                  # Pause nach „online“ läuft
    clock.t += 4
    tick(h)
    assert calls == []
    clock.t += 2
    tick(h)
    assert calls == [("POST", "/api/steam/games/730/launch", {"force": False})]
    assert h.pending_launch is None and results[0]["ok"] is True and h.message()["pending_launch"] is None
    tick(h)
    assert len(calls) == 1                                                                              # nur einmal
    assert h.message()["launch_result"]["ok"] is True
    clock.t += 121
    assert h.message()["launch_result"] is None                                                         # Ergebnis verschwindet nach 2 Minuten


def test_cold_mode_waits_longer_before_starting(rig):
    clock, h, calls, results, _ = rig
    h.wake_mode, h.wake_timeout, h.launch_delay = wake_params({"wake_mode": "cold"})
    h.queue_launch(730, "X")
    assert h.public_pending()["left_s"] == 300 + 120
    h.status, h.features = "online", ["steam"]
    tick(h)
    clock.t += 24
    tick(h)
    assert calls == []
    clock.t += 2
    tick(h)
    assert len(calls) == 1


def test_pc_dropping_out_again_restarts_the_pause(rig):
    clock, h, calls, _, _ = rig
    h.queue_launch(730, "X")
    h.status, h.features = "online", ["steam"]
    tick(h)
    clock.t += 4
    h.status = "waking"
    tick(h)
    h.status = "online"
    tick(h)
    clock.t += 4
    tick(h)
    assert calls == []                                                                                  # Pause begann von vorn


def test_expiry_reports_failure_and_never_starts(rig):
    clock, h, calls, results, _ = rig
    h.queue_launch(730, "X")
    clock.t += 241
    tick(h)
    assert calls == [] and h.pending_launch is None
    assert results[0]["ok"] is False and "nicht rechtzeitig" in results[0]["message"]
    h.status, h.features = "online", ["steam"]
    clock.t += 60
    tick(h)
    assert calls == []                                                                                  # abgelaufen bleibt abgelaufen


def test_agent_not_ready_is_retried_but_refusals_are_final(rig):
    clock, h, calls, results, answers = rig
    h.status, h.features = "online", ["steam"]
    h.launch_delay = 0
    h.queue_launch(730, "X")
    answers += [(502, {"detail": "Agent nicht erreichbar"}), (200, {"ok": True})]
    tick(h)
    assert len(calls) == 1 and h.pending_launch is not None
    tick(h)
    assert len(calls) == 1                                                                              # erst nach 5 s wieder
    clock.t += 5
    tick(h)
    assert len(calls) == 2 and results[-1]["ok"] is True
    h.queue_launch(440, "Y")
    answers.append((409, {"detail": "Es läuft bereits ein anderes Spiel: Z"}))
    tick(h)
    assert results[-1]["ok"] is False and "anderes Spiel" in results[-1]["message"] and h.pending_launch is None
    h.queue_launch(1, "N")
    answers.append((404, {"detail": "Spiel nicht installiert"}))
    tick(h)
    assert results[-1]["message"] == "Spiel nicht installiert"


def test_cancel_only_matches_the_queued_game(rig):
    _, h, calls, _, _ = rig
    h.queue_launch(730, "X")
    assert h.cancel_launch(999) is False and h.pending_launch is not None
    assert h.cancel_launch(730) is True and h.pending_launch is None
    assert h.cancel_launch() is False


# ---------------------------------------------------------------- Endpunkte
OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "agent-secret", "mac": "AA:BB:CC:DD:EE:FF"},
                                       {"name": "Ohne-MAC", "host": "10.0.0.6", "token": "t2"}]}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    sent, calls = [], []
    monkeypatch.setattr(main_mod, "send_magic_packet", lambda mac, ip: sent.append((mac, ip)))
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        for pid, h in c.app.state.hubs.items():
            h.status = "offline"

            async def fake(method, path, params=None, body=None, timeout=15.0, pid=pid):
                calls.append({"pc": pid, "method": method, "path": path, "body": body})
                if path.count("/") == 4 and path.startswith("/api/steam/games/") and not path.endswith("/launch"):
                    return 200, json.dumps({"appid": 730, "name": "Counter-Strike 2"}).encode(), "application/json"
                return 200, json.dumps({"ok": True}).encode(), "application/json"

            async def fetch(method, path, params=None, body=None, timeout=15.0, extra_headers=None, fake=fake):
                code, content, ctype = await fake(method, path, params, body, timeout)
                return code, content, ctype, {}

            h.agent_request, h.agent_fetch = fake, fetch
        c.sent, c.calls = sent, calls
        yield c


def view_token(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    return client.post("/api/pair/redeem", json={"code": code}).json()["token"]


def hub_of(client, pid="gaming-pc"):
    return client.app.state.hubs[pid]


def test_wake_and_launch_from_offline_sends_packet_and_queues(client):
    r = client.post("/api/steam/games/730/launch?wake=true&name=Counter-Strike%202", headers=MASTER)
    assert r.status_code == 202 and r.json()["pending"] is True and r.json()["mode"] == "standby"
    assert client.sent == [("AA:BB:CC:DD:EE:FF", "255.255.255.255")]
    h = hub_of(client)
    assert h.status == "waking" and h.pending_launch["name"] == "Counter-Strike 2"
    assert client.calls == []                                                                           # nichts geht an den (noch aus) Agenten
    st = client.get("/api/status", headers=MASTER).json()
    assert st["pending_launch"]["appid"] == 730 and st["status"] == "waking" and st["wake_mode"] == "standby"
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert "Aufwecken und starten" in raw and "Counter-Strike 2 (730)" in raw


def test_wake_launch_while_already_waking_does_not_send_a_second_packet(client):
    client.post("/api/wake", headers=MASTER)
    assert len(client.sent) == 1
    assert client.post("/api/steam/games/440/launch?wake=true&name=TF2", headers=MASTER).status_code == 202
    assert len(client.sent) == 1 and hub_of(client).pending_launch["appid"] == 440


def test_wake_param_is_ignored_when_the_pc_is_online(client):
    h = hub_of(client)
    h.status = "online"
    assert client.post("/api/steam/games/730/launch?wake=true&name=X", headers=MASTER, json={"force": True}).status_code == 200
    assert client.calls[-1]["path"] == "/api/steam/games/730/launch" and client.calls[-1]["body"] == {"force": True}
    assert client.sent == [] and h.pending_launch is None


def test_offline_without_wake_param_is_still_409_and_missing_mac_is_400(client):
    assert client.post("/api/steam/games/730/launch", headers=MASTER).status_code == 409
    assert client.post("/api/steam/games/730/launch?wake=true&pc=ohne-mac", headers=MASTER).status_code == 400
    assert hub_of(client, "ohne-mac").pending_launch is None and client.sent == []


def test_name_is_cleaned_and_limited_and_appid_validated(client):
    client.post("/api/steam/games/730/launch?wake=true&name=" + "A%0AB\x00".replace("\x00", "") + "x" * 200, headers=MASTER)
    n = hub_of(client).pending_launch["name"]
    assert "\n" not in n and len(n) <= 80
    assert client.post("/api/steam/games/0/launch?wake=true", headers=MASTER).status_code == 400
    assert client.post("/api/steam/games/99999999999/launch?wake=true", headers=MASTER).status_code == 400


def test_cancel_pending_launch_and_rights(client):
    client.post("/api/steam/games/730/launch?wake=true&name=X", headers=MASTER)
    v = {"Authorization": "Bearer " + view_token(client)}
    assert client.post("/api/steam/games/730/launch?wake=true", headers=v).status_code == 403          # Nur-Ansicht darf nicht aufwecken
    assert client.delete("/api/steam/games/730/launch", headers=v).status_code == 403
    assert client.delete("/api/steam/games/730/launch").status_code == 401
    assert client.delete("/api/steam/games/999/launch", headers=MASTER).json() == {"ok": True, "cancelled": False}
    assert hub_of(client).pending_launch is not None
    assert client.delete("/api/steam/games/730/launch", headers=MASTER).json() == {"ok": True, "cancelled": True}
    assert hub_of(client).pending_launch is None
    assert "abgebrochen" in json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)


def test_finished_launch_is_written_to_the_audit_log(client):
    h = hub_of(client)
    h.queue_launch(730, "Counter-Strike 2")
    h.status, h.features, h.launch_delay = "online", ["steam"], 0
    asyncio.run(h._launch_tick())
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert "Spiel gestartet (nach Aufwecken)" in raw and "Counter-Strike 2 (730)" in raw


def test_standby_action_is_allowed_and_expected_to_take_the_pc_offline(client, monkeypatch):
    h = hub_of(client)
    h.status = "online"
    seen = []

    async def fake_action(name, body):
        seen.append(name)
        return 200, {"ok": True}

    h.agent_action = fake_action
    assert client.post("/api/action/standby", headers=MASTER).status_code == 200 and seen == ["standby"]
    assert client.post("/api/action/format_c", headers=MASTER).status_code == 404
