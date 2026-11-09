import json
import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "agent-secret"},
                                       {"name": "KI-PC", "host": "10.0.0.6", "token": "t2"}]}
MASTER = {"Authorization": "Bearer master"}


@pytest.fixture()
def client(tmp_path):
    calls = []
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c:
        for pid, hub in c.app.state.hubs.items():
            hub.status = "online"

            async def fake(method, path, params=None, body=None, timeout=15.0, pid=pid):
                calls.append({"pc": pid, "method": method, "path": path, "params": params, "body": body})
                if path.endswith("/thumb") or path.endswith("/screenshot"):
                    return 200, b"\xff\xd8\xffJPEGDATA", "image/jpeg"
                return 200, json.dumps({"ok": True}).encode(), "application/json"

            hub.agent_request = fake

            async def fake_action(name, body, pid=pid):
                calls.append({"pc": pid, "action": name, "body": body})
                return 200, {"ok": True}

            hub.agent_action = fake_action
        c.calls = calls
        yield c


def view_token(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    return client.post("/api/pair/redeem", json={"code": code}).json()["token"]


def test_requests_are_relayed_to_the_selected_pc_without_leaking_the_agent_token(client):
    r = client.post("/api/power-plan?pc=ki-pc", headers=MASTER, json={"timer_minutes": 30, "mode": "sleep", "boese": "x"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.calls[-1] == {"pc": "ki-pc", "method": "POST", "path": "/api/power-plan", "params": None,
                                "body": {"timer_minutes": 30, "mode": "sleep"}}          # unbekannte Felder werden verworfen
    client.get("/api/processes?sort=vram&limit=5&evil=1", headers=MASTER)
    assert client.calls[-1]["pc"] == "gaming-pc" and client.calls[-1]["params"] == {"sort": "vram", "limit": "5"}
    assert "agent-secret" not in json.dumps(client.calls)


def test_offline_pc_gives_409_and_unknown_pc_404(client):
    client.app.state.hubs["gaming-pc"].status = "offline"
    assert client.get("/api/programs", headers=MASTER).status_code == 409
    assert client.get("/api/programs?pc=ki-pc", headers=MASTER).status_code == 200
    assert client.get("/api/programs?pc=nix", headers=MASTER).status_code == 404


def test_view_only_devices_may_read_gallery_history_plan_but_nothing_else(client):
    h = {"Authorization": "Bearer " + view_token(client)}
    for path in ("/api/gallery", "/api/gallery/thumb?name=a.png", "/api/gallery/file?name=a.png", "/api/jobs/history", "/api/power-plan"):
        assert client.get(path, headers=h).status_code == 200, path
    for method, path in (("GET", "/api/programs"), ("GET", "/api/processes"), ("GET", "/api/screenshot"), ("GET", "/api/clipboard"),
                         ("POST", "/api/programs/comfy/start"), ("POST", "/api/processes/12/kill"), ("POST", "/api/job/a/cancel"),
                         ("POST", "/api/power-plan"), ("DELETE", "/api/power-plan"), ("POST", "/api/action/clipboard_set")):
        assert client.request(method, path, headers=h).status_code == 403, path


def test_gallery_only_passes_known_parameters(client):
    client.get("/api/gallery/file?folder=sig&name=a/b.png&download=true&pc=ki-pc&token=x&path=/etc", headers=MASTER)
    last = client.calls[-1]
    assert last["pc"] == "ki-pc" and last["params"] == {"folder": "sig", "name": "a/b.png", "download": "true"}


def test_binary_responses_keep_their_content_type(client):
    r = client.get("/api/gallery/thumb?name=a.png", headers=MASTER)
    assert r.headers["content-type"] == "image/jpeg" and r.content.startswith(b"\xff\xd8\xff") and r.headers["cache-control"] == "no-store"


def test_ids_are_validated_and_ops_limited(client):
    assert client.post("/api/programs/comfy/start", headers=MASTER).status_code == 200
    assert client.post("/api/programs/comfy/format", headers=MASTER).status_code == 404
    n = len(client.calls)
    assert client.post("/api/programs/..%2Fx/start", headers=MASTER).status_code in (404, 405)      # Pfad passt auf keine Route
    assert len(client.calls) == n                                                              # und wurde nie weitergereicht
    assert client.post("/api/job/a$b/cancel", headers=MASTER).status_code == 404
    assert client.post("/api/job/job-1/cancel", headers=MASTER).status_code == 200


def test_audit_records_actions_but_never_clipboard_text(client):
    client.post("/api/action/clipboard_set", headers=MASTER, json={"text": "MEIN-GEHEIMES-PASSWORT"})
    client.post("/api/processes/123/kill", headers=MASTER)
    client.post("/api/programs/comfy/stop", headers=MASTER)
    client.get("/api/screenshot", headers=MASTER)
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert "GEHEIMES" not in raw and "text=22 Zeichen" in raw
    for what in ("Prozess beendet", "Programm beendet", "Screenshot"):
        assert what in raw
    assert "PID 123" in raw


def test_features_come_from_the_agent_health(client):
    hub = client.app.state.hubs["gaming-pc"]
    hub.features = ["power_plan", "gallery"]
    assert client.get("/api/status", headers=MASTER).json()["features"] == ["power_plan", "gallery"]
    assert client.get("/api/status?pc=ki-pc", headers=MASTER).json()["features"] == []          # älterer Agent


def test_new_actions_are_allowed(client):
    assert client.post("/api/action/monitor_off", headers=MASTER).status_code == 200
    assert client.post("/api/action/clipboard_set", headers=MASTER, json={"text": "x"}).status_code == 200
