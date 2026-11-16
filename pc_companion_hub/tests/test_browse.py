"""Dateibrowser-Relay (Phase 10.9): nur mit Schreibrecht, nur erlaubte Parameter, Downloads im Protokoll."""
import json
import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MASTER = {"Authorization": "Bearer master"}
OPTS = {"ui_token": "master", "pcs": [{"name": "Gaming-PC", "host": "10.0.0.5", "token": "agent-secret"}]}


@pytest.fixture()
def client(tmp_path):
    calls = []
    with TestClient(create_app(json.loads(json.dumps(OPTS)), data_dir=tmp_path)) as c:
        for h in c.app.state.hubs.values():
            h.status = "online"

            async def fetch(method, path, params=None, body=None, timeout=15.0, extra_headers=None):
                calls.append((method, path, params))
                if path.endswith("/file"):
                    return 200, b"hallo", "application/octet-stream", {}
                return 200, json.dumps({"folder": "Doku", "path": "", "items": [], "total": 0, "truncated": False, "folders": ["Doku"]}).encode(), "application/json", {}

            h.agent_fetch = fetch
        c.calls = calls
        yield c


def view_headers(client):
    code = client.post("/api/pair", headers=MASTER, json={"base": "http://x", "role": "view"}).json()["code"]
    return {"Authorization": "Bearer " + client.post("/api/pair/redeem", json={"code": code}).json()["token"]}


def test_listing_and_download_relay_only_known_parameters_and_log_the_download(client):
    assert client.get("/api/browse?folder=Doku&path=Bilder&evil=1", headers=MASTER).status_code == 200
    assert client.calls[-1] == ("GET", "/api/browse", {"folder": "Doku", "path": "Bilder"})
    r = client.get("/api/browse/file?folder=Doku&path=Bilder/a.png&download=true&x=y", headers=MASTER)
    assert r.status_code == 200 and r.content == b"hallo"
    assert client.calls[-1][2] == {"folder": "Doku", "path": "Bilder/a.png", "download": "true"}
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    assert "Datei geladen" in raw and "Doku/Bilder/a.png" in raw


def test_view_only_devices_and_anonymous_are_refused(client):
    v = view_headers(client)
    for path in ("/api/browse", "/api/browse/file?path=a"):
        assert client.get(path, headers=v).status_code == 403
        assert client.get(path).status_code == 401
    assert client.calls == []


def test_offline_pc_gives_409(client):
    for h in client.app.state.hubs.values():
        h.status = "offline"
    assert client.get("/api/browse", headers=MASTER).status_code == 409
