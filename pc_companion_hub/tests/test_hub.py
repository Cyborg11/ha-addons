import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.hub import WAKE_TIMEOUT_S, compute_status
from app.main import create_app
from app.wol import magic_packet

OPTS = {"agent_host": "", "agent_token": "a", "ui_token": "ui", "pc_mac": "AA:BB:CC:DD:EE:FF",
        "broadcast_ip": "127.0.0.1"}
AUTH = {"Authorization": "Bearer ui"}


def test_magic_packet():
    p = magic_packet("aa-bb-cc-dd-ee-ff")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("aabbccddeeff")
    with pytest.raises(ValueError):
        magic_packet("zz")


def test_compute_status():
    assert compute_status(True, 100.0, 101.0) == "online"
    assert compute_status(False, None, 101.0) == "offline"
    assert compute_status(False, 100.0, 110.0) == "waking"
    assert compute_status(False, 100.0, 100.0 + WAKE_TIMEOUT_S + 1) == "offline"


@pytest.fixture()
def client():
    with TestClient(create_app(dict(OPTS))) as c:
        yield c


def test_api_requires_ui_token(client):
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/wake").status_code == 401
    assert client.get("/api/status", headers=AUTH).json()["status"] == "offline"


def test_wake_sets_waking(client):
    r = client.post("/api/wake", headers=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "waking"
    assert client.get("/api/status", headers=AUTH).json()["status"] == "waking"


def test_wake_without_mac():
    opts = dict(OPTS, pc_mac="")
    with TestClient(create_app(opts)) as c:
        assert c.post("/api/wake", headers=AUTH).status_code == 400


def test_empty_ui_token_rejects_everything():
    with TestClient(create_app(dict(OPTS, ui_token=""))) as c:
        assert c.get("/api/status", headers={"Authorization": "Bearer "}).status_code == 401


def test_ws_auth_and_initial_message(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=bad"):
            pass
    with client.websocket_connect("/ws?token=ui") as ws:
        assert ws.receive_json()["pcs"] and ws.receive_json()["status"] == "offline"


def test_static_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "PC-Companion" in r.text
    assert client.get("/manifest.webmanifest").status_code == 200


def test_action_requires_auth_and_online(client):
    assert client.post("/api/action/lock").status_code == 401
    assert client.post("/api/action/lock", headers=AUTH).status_code == 409  # PC offline
    assert client.post("/api/action/rm_rf", headers=AUTH).status_code == 404


def test_restart_agent_action_is_allowed(client):
    hub = client.app.state.hub
    hub.status = "online"
    seen = []

    async def fake(name, body):
        seen.append(name)
        return 200, {"ok": True, "action": name}

    hub.agent_action = fake
    assert client.post("/api/action/restart_agent", headers=AUTH).status_code == 200
    assert seen == ["restart_agent"]


def test_action_is_forwarded(client):
    hub = client.app.state.hub
    hub.status = "online"
    seen = []

    async def fake(name, body):
        seen.append((name, body))
        return 200, {"ok": True, "action": name}

    hub.agent_action = fake
    r = client.post("/api/action/volume", headers=AUTH, json={"level": 25})
    assert r.status_code == 200 and seen == [("volume", {"level": 25})]


def test_agent_error_is_passed_through(client):
    hub = client.app.state.hub
    hub.status = "online"

    async def fake(name, body):
        return 400, {"detail": "Nur http(s)-URLs erlaubt"}

    hub.agent_action = fake
    r = client.post("/api/action/open_url", headers=AUTH, json={"url": "file:///x"})
    assert r.status_code == 400 and "http" in r.json()["detail"]


def test_upload_requires_auth_and_online(client):
    assert client.post("/api/upload?filename=a.txt", content=b"x").status_code == 401
    assert client.post("/api/upload?filename=a.txt", content=b"x", headers=AUTH).status_code == 409
    assert client.get("/api/upload/targets", headers=AUTH).status_code == 409


def test_upload_streams_body_to_agent(client):
    hub = client.app.state.hub
    hub.status = "online"
    got = {}

    async def fake(stream, filename, target, content_length):
        got["body"] = b"".join([c async for c in stream])
        got["args"] = (filename, target, content_length)
        return 200, {"ok": True, "filename": filename, "size": len(got["body"])}

    hub.agent_upload = fake
    r = client.post("/api/upload?filename=foto.jpg&target=nas", content=b"abc" * 1000, headers=AUTH)
    assert r.status_code == 200 and r.json()["size"] == 3000
    assert got["body"] == b"abc" * 1000 and got["args"] == ("foto.jpg", "nas", "3000")


def test_tools_in_message_only_http_urls():
    opts = dict(OPTS, tools=[
        {"name": "Master Dashboard", "url": "http://100.1.2.3:7880"},
        {"name": "Böse", "url": "javascript:alert(1)"},
        {"name": "", "url": "http://x"},
        {"name": "Ohne Schema", "url": "ftp://x"},
    ])
    with TestClient(create_app(opts)) as c:
        tools = c.get("/api/status", headers=AUTH).json()["tools"]
    assert tools == [{"name": "Master Dashboard", "url": "http://100.1.2.3:7880"}]


def test_preview_proxy_auth_and_forward(client):
    assert client.get("/api/job/abc/preview").status_code == 401
    assert client.get("/api/job/abc/preview", headers=AUTH).status_code == 404  # PC offline
    hub = client.app.state.hub
    hub.status = "online"

    async def fake(job_id):
        return 200, b"PNGDATA", "image/png"

    hub.agent_job_preview = fake
    r = client.get("/api/job/abc/preview", headers=AUTH)
    assert r.status_code == 200 and r.content == b"PNGDATA" and r.headers["content-type"] == "image/png"
    assert client.get("/api/job/..%2Fx/preview", headers=AUTH).status_code == 404


def test_brief_stats_and_offline_message(tmp_path):
    from app.hub import Hub, brief_stats
    snap = {"gpu": {"util_pct": 40, "temp_c": 61}, "cpu": {"util_pct": 12.6}, "ram": {"used_mb": 8000, "total_mb": 32000}, "uptime_s": 99}
    assert brief_stats(snap) == {"cpu": 13, "ram": 25, "gpu": 40, "temp": 61, "uptime_s": 99}
    assert brief_stats({}) == {"cpu": None, "ram": None, "gpu": None, "temp": None, "uptime_s": None}
    h = Hub({"agent_host": "x"}, "pc1", "Test")
    m = h.message()
    assert m["last_seen"] is None and m["last_stats"] is None and m["waking_total"] == WAKE_TIMEOUT_S


def test_last_seen_survives_restart_through_history(tmp_path):
    from app import history as hist
    h = hist.History(tmp_path / "h.db")
    assert h.last_t("pc1") is None
    h.db.execute("INSERT INTO samples VALUES ('pc1', 1234, 1,1,1,1,1,1)")
    h.db.commit()
    assert h.last_t("pc1") == 1234 and h.last_t("anderer") is None
