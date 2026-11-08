import json
import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import audit as audit_mod, auth
from app.main import create_app

OPTS = {"ui_token": "master", "pin": "482913", "broadcast_ip": "127.0.0.1", "pc_mac": "AA:BB:CC:DD:EE:FF",
        "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "t", "mac": "AA:BB:CC:DD:EE:FF"}]}
MASTER = {"Authorization": "Bearer master"}


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c:
        hub = c.app.state.hub
        hub.status = "online"

        async def fake_action(name, body):
            return 200, {"ok": True}

        async def fake_targets():
            return 200, {"targets": ["a"], "default": "a", "max_mb": 1}

        hub.agent_action, hub.agent_upload_targets = fake_action, fake_targets
        yield c


def pair_device(client, role, name="Tablet"):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": role}).json()["code"]
    r = client.post("/api/pair/redeem", json={"code": code, "name": name}).json()
    return r["token"], r["device"]


def bearer(t):
    return {"Authorization": "Bearer " + t}


def test_view_device_can_look_but_not_touch(client):
    token, dev = pair_device(client, "view")
    assert dev["role"] == "view"
    h = bearer(token)
    assert client.get("/api/status", headers=h).status_code == 200
    assert client.get("/api/pcs", headers=h).json()["role"] == "view"
    assert client.post("/api/action/lock", headers=h).status_code == 403
    assert client.post("/api/wake", headers=h).status_code == 403
    assert client.get("/api/upload/targets", headers=h).status_code == 403
    assert client.post("/api/pair", headers=h, json={"base": "http://x"}).status_code == 403
    assert client.get("/api/audit", headers=h).status_code == 403
    assert client.patch("/api/devices/" + dev["id"], headers=h, json={"role": "full"}).status_code == 403   # keine Selbstbeförderung


def test_view_device_sees_and_removes_only_itself(client):
    token, dev = pair_device(client, "view")
    pair_device(client, "full", "Handy")
    lst = client.get("/api/devices", headers=bearer(token)).json()
    assert [d["id"] for d in lst["devices"]] == [dev["id"]] and lst["role"] == "view"
    other = next(d["id"] for d in client.get("/api/devices", headers=MASTER).json()["devices"] if d["name"] == "Handy")
    assert client.delete("/api/devices/" + other, headers=bearer(token)).status_code == 403
    assert client.delete("/api/devices/" + dev["id"], headers=bearer(token)).status_code == 200


def test_websocket_reports_role(client):
    token, _ = pair_device(client, "view")
    with client.websocket_connect("/ws?token=" + token) as ws:
        assert ws.receive_json()["role"] == "view"
    with client.websocket_connect("/ws?token=master") as ws:
        assert ws.receive_json()["role"] == "full"


def test_role_can_be_changed_by_full_access(client):
    token, dev = pair_device(client, "view")
    assert client.post("/api/action/lock", headers=bearer(token)).status_code == 403
    assert client.patch("/api/devices/" + dev["id"], headers=MASTER, json={"role": "full"}).status_code == 200
    assert client.post("/api/action/lock", headers=bearer(token)).status_code == 200
    assert client.patch("/api/devices/" + dev["id"], headers=MASTER, json={"role": "admin"}).status_code == 400
    assert client.patch("/api/devices/nope", headers=MASTER, json={"role": "view"}).status_code == 404


def test_pin_login_is_full_and_old_devices_default_to_full(tmp_path):
    (tmp_path / "devices.json").write_text(json.dumps({"devices": [{"id": "old1", "name": "Alt", "hash": auth.hash_token("alt")}]}))
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c:
        assert c.get("/api/pcs", headers=bearer("alt")).json()["role"] == "full"
        assert c.post("/api/login", json={"secret": "482913"}).json()["device"]["role"] == "full"


def test_actions_are_audited_with_who_pc_and_result(client):
    token, _ = pair_device(client, "full", "Pixel")
    client.post("/api/action/volume", headers=bearer(token), json={"level": 30})
    client.post("/api/action/lock", headers=MASTER)
    client.post("/api/wake", headers=MASTER)
    entries = client.get("/api/audit", headers=MASTER).json()["entries"]
    by = {e["what"]: e for e in entries}
    assert by["Aktion: volume"]["who"] == "Pixel" and by["Aktion: volume"]["pc"] == "Gaming-PC" and "level=30" in by["Aktion: volume"]["detail"]
    assert by["Aktion: lock"]["who"] == "Hauptschlüssel" and by["Aktion: lock"]["ok"] is True
    assert "PC aufgeweckt" in by and "Gerät gekoppelt (QR)" in by and "Kopplung erzeugt" in by
    assert entries[0]["t"] >= entries[-1]["t"]                       # neueste zuerst


def test_failed_login_and_pairing_are_audited_without_secrets(client):
    client.post("/api/login", json={"secret": "geheim-falsch"})
    client.post("/api/pair/redeem", json={"code": "geratener-code"})
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json())
    assert "Anmeldung fehlgeschlagen" in raw and "Kopplung fehlgeschlagen" in raw
    assert "geheim-falsch" not in raw and "geratener-code" not in raw


def test_failed_action_is_marked(client):
    async def broken(name, body):
        return 502, {"detail": "x"}

    client.app.state.hub.agent_action = broken
    client.post("/api/action/lock", headers=MASTER)
    assert client.get("/api/audit", headers=MASTER).json()["entries"][0]["ok"] is False


def test_audit_log_is_truncated_and_survives_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_mod, "MAX_LINES", 5)
    monkeypatch.setattr(audit_mod, "SHRINK_AT", 8)
    log = audit_mod.AuditLog(tmp_path / "a.log")
    for i in range(12):
        log.add("x", f"e{i}")
    lines = (tmp_path / "a.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 8 and json.loads(lines[-1])["what"] == "e11"
    with (tmp_path / "a.log").open("a", encoding="utf-8") as f:
        f.write("kaputt{\n")
    tail = log.tail(50)                                              # kaputte Zeile wird übersprungen, kein Fehler
    assert tail[0]["what"] == "e11" and all("what" in e for e in tail)
