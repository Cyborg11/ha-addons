"""Fernbedienung light (Phase 10.10), Hub: nur mit confirm_pin, PIN beim Öffnen, Sitzung mit Zeitlimit, nur erlaubte Felder, Protokoll."""
import json
import os
import time

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MASTER = {"Authorization": "Bearer master"}
PIN = {"X-Confirm-PIN": "424242"}


def build(tmp_path, pin=True, feature=True):
    opts = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "agent-secret"}]}
    if pin:
        opts["confirm_pin"] = "424242"
    calls = []
    c = TestClient(create_app(opts, data_dir=tmp_path))
    c.__enter__()
    for h in c.app.state.hubs.values():
        h.status = "online"
        h.features = ["remote_input"] if feature else []

        async def req(method, path, params=None, body=None, timeout=15.0):
            calls.append((method, path, body))
            if path == "/api/remote/session" and method == "POST":
                return 200, json.dumps({"open": True, "left_s": body["minutes"] * 60}).encode(), "application/json"
            return 200, json.dumps({"ok": True}).encode(), "application/json"

        h.agent_request = req
    c.calls = calls
    return c


@pytest.fixture()
def client(tmp_path):
    c = build(tmp_path)
    yield c
    c.__exit__(None, None, None)


def audit_text(c):
    return json.dumps(c.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)


def test_open_needs_pin_then_inputs_flow_only_with_whitelisted_fields(client):
    assert client.post("/api/remote/session", headers=MASTER, json={"minutes": 5}).status_code == 428
    assert client.post("/api/remote/session", headers={**MASTER, "X-Confirm-PIN": "falsch"}, json={"minutes": 5}).status_code == 403
    assert client.calls == []
    r = client.post("/api/remote/session", headers={**MASTER, **PIN}, json={"minutes": 5})
    assert r.status_code == 200 and r.json()["left_s"] == 300
    st = client.get("/api/remote", headers=MASTER).json()
    assert st["open"] is True and st["available"] is True and 295 <= st["left_s"] <= 300
    r = client.post("/api/remote/input", headers=MASTER, json={"type": "move", "dx": 3, "dy": 4, "evil": "x", "cmd": "calc"})
    assert r.status_code == 200
    assert client.calls[-1] == ("POST", "/api/remote/input", {"type": "move", "dx": 3, "dy": 4})
    a = audit_text(client)
    assert "Fernbedienung geöffnet" in a and "5 Min." in a


def test_no_session_no_input_and_closing_ends_it(client):
    assert client.post("/api/remote/input", headers=MASTER, json={"type": "click"}).status_code == 403
    client.post("/api/remote/session", headers={**MASTER, **PIN}, json={})
    assert client.post("/api/remote/input", headers=MASTER, json={"type": "click"}).status_code == 200
    assert client.delete("/api/remote/session", headers=MASTER).json()["open"] is False
    assert ("DELETE", "/api/remote/session", None) in client.calls
    assert client.post("/api/remote/input", headers=MASTER, json={"type": "click"}).status_code == 403
    assert "Fernbedienung beendet" in audit_text(client)


def test_hub_side_session_expires(client):
    client.post("/api/remote/session", headers={**MASTER, **PIN}, json={"minutes": 1})
    # Ablauf simulieren: Zeit läuft über das Sitzungsende hinaus
    real = time.time
    try:
        time.time = lambda: real() + 61
        assert client.post("/api/remote/input", headers=MASTER, json={"type": "click"}).status_code == 403
        assert client.get("/api/remote", headers=MASTER).json()["open"] is False
    finally:
        time.time = real


def test_minutes_are_validated(client):
    for bad in (0, 16, "5", True, 2.5):
        assert client.post("/api/remote/session", headers={**MASTER, **PIN}, json={"minutes": bad}).status_code == 400


def test_without_confirm_pin_the_remote_is_refused(tmp_path):
    c = build(tmp_path, pin=False)
    try:
        r = c.post("/api/remote/session", headers=MASTER, json={"minutes": 5})
        assert r.status_code == 403 and "PIN" in r.json()["detail"]
        assert c.get("/api/remote", headers=MASTER).json()["available"] is False
        assert c.calls == []
    finally:
        c.__exit__(None, None, None)


def test_agent_without_the_feature_and_offline_pc(tmp_path):
    c = build(tmp_path, feature=False)
    try:
        assert c.post("/api/remote/session", headers={**MASTER, **PIN}, json={}).status_code == 404
        for h in c.app.state.hubs.values():
            h.status = "offline"
        assert c.post("/api/remote/session", headers={**MASTER, **PIN}, json={}).status_code == 409
    finally:
        c.__exit__(None, None, None)


def test_view_only_devices_and_anonymous_are_refused(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    v = {"Authorization": "Bearer " + client.post("/api/pair/redeem", json={"code": code}).json()["token"], **PIN}
    for method, path in (("get", "/api/remote"), ("post", "/api/remote/session"), ("post", "/api/remote/input"), ("delete", "/api/remote/session")):
        assert client.request(method.upper(), path, headers=v, json={} if method == "post" else None).status_code == 403
        assert client.request(method.upper(), path).status_code == 401
    assert client.calls == []
