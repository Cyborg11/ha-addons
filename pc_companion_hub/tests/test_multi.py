import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import build_pcs, create_app, slugify

AUTH = {"Authorization": "Bearer ui"}
BASE = {"ui_token": "ui", "broadcast_ip": "127.0.0.1",
        "tools": [{"name": "Global", "url": "http://g"}],
        "pcs": [
            {"name": "Gaming-PC", "host": "10.0.0.5", "port": 8765, "token": "tok-a", "mac": "AA:BB:CC:DD:EE:01"},
            {"name": "Gaming PC", "host": "10.0.0.6", "token": "tok-b", "mac": "AA:BB:CC:DD:EE:02",
             "tools": [{"name": "Nur PC2", "url": "http://p2"}]},
            {"name": "Ohne Adresse", "host": ""},
        ]}


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(dict(BASE), data_dir=tmp_path)) as c:
        yield c


def test_slugify():
    assert slugify("Gaming-PC") == "gaming-pc" and slugify("Büro Rechner!") == "b-ro-rechner" and slugify("!!!") == "pc"


def test_build_pcs_new_form():
    pcs = build_pcs(dict(BASE))
    assert [(p[0], p[1]) for p in pcs] == [("gaming-pc", "Gaming-PC"), ("gaming-pc-2", "Gaming PC")]   # eindeutige IDs, leere Adresse übersprungen
    a, b = pcs[0][2], pcs[1][2]
    assert (a["agent_host"], a["agent_port"], a["agent_token"], a["pc_mac"]) == ("10.0.0.5", 8765, "tok-a", "AA:BB:CC:DD:EE:01")
    assert b["agent_port"] == 8765 and b["tools"][0]["name"] == "Nur PC2" and a["tools"][0]["name"] == "Global"


def test_build_pcs_legacy_form():
    pcs = build_pcs({"agent_host": "h", "agent_port": 9, "agent_token": "t", "pc_mac": "m"})
    assert len(pcs) == 1 and pcs[0][0] == "pc1" and pcs[0][2]["agent_host"] == "h"
    assert len(build_pcs({})) == 1                      # nichts konfiguriert: ein leerer PC wie bisher


def test_pcs_endpoint_and_default(client):
    assert client.get("/api/pcs").status_code == 401
    d = client.get("/api/pcs", headers=AUTH).json()
    assert d["default"] == "gaming-pc" and [p["id"] for p in d["pcs"]] == ["gaming-pc", "gaming-pc-2"]
    assert client.get("/api/status", headers=AUTH).json()["pc"] == "gaming-pc"
    assert client.get("/api/status?pc=gaming-pc-2", headers=AUTH).json()["name"] == "Gaming PC"
    assert client.get("/api/status?pc=gibts-nicht", headers=AUTH).status_code == 404


def test_websocket_sends_list_then_every_pc(client):
    with client.websocket_connect("/ws?token=ui") as ws:
        first = ws.receive_json()
        assert [p["id"] for p in first["pcs"]] == ["gaming-pc", "gaming-pc-2"] and first["default"] == "gaming-pc"
        msgs = [ws.receive_json(), ws.receive_json()]
        assert [m["pc"] for m in msgs] == ["gaming-pc", "gaming-pc-2"]
        assert msgs[1]["tools"][0]["name"] == "Nur PC2" and msgs[1]["wol_configured"] is True


def test_actions_go_to_the_selected_pc(client):
    calls = []
    for pid, h in client.app.state.hubs.items():
        h.status = "online"

        async def fake(name, body, pid=pid):
            calls.append((pid, name))
            return 200, {"ok": True}

        h.agent_action = fake
    assert client.post("/api/action/lock", headers=AUTH).status_code == 200                 # ohne pc: Standard-PC
    assert client.post("/api/action/lock?pc=gaming-pc-2", headers=AUTH).status_code == 200
    assert client.post("/api/action/lock?pc=x", headers=AUTH).status_code == 404
    assert calls == [("gaming-pc", "lock"), ("gaming-pc-2", "lock")]


def test_offline_state_is_per_pc(client):
    client.app.state.hubs["gaming-pc-2"].status = "online"
    assert client.post("/api/action/lock?pc=gaming-pc", headers=AUTH).status_code == 409
    assert client.get("/api/status?pc=gaming-pc-2", headers=AUTH).json()["status"] == "online"
    assert client.get("/api/status?pc=gaming-pc", headers=AUTH).json()["status"] == "offline"


def test_wake_uses_mac_of_selected_pc(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.main.send_magic_packet", lambda mac, bc: sent.append((mac, bc)))
    assert client.post("/api/wake?pc=gaming-pc-2", headers=AUTH).status_code == 200
    assert sent == [("AA:BB:CC:DD:EE:02", "127.0.0.1")]
    assert client.app.state.hubs["gaming-pc-2"].status == "waking"
    assert client.app.state.hubs["gaming-pc"].status == "offline"     # anderer PC unberührt


def test_wake_without_mac(tmp_path):
    opts = {"ui_token": "ui", "pcs": [{"name": "A", "host": "h", "token": "t"}]}
    with TestClient(create_app(opts, data_dir=tmp_path)) as c:
        r = c.post("/api/wake", headers=AUTH)
        assert r.status_code == 400
