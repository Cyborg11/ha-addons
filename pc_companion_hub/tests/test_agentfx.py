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
                if "/api/steam/games/" in path and path.count("/") == 4 and not path.endswith("/launch"):
                    return 200, json.dumps({"appid": 730, "name": "Counter-Strike 2"}).encode(), "application/json"
                return 200, json.dumps({"ok": True}).encode(), "application/json"

            hub.agent_request = fake

            async def fetch(method, path, params=None, body=None, timeout=15.0, extra_headers=None, pid=pid, fake=fake):
                if "/api/steam/art/" in path:
                    calls.append({"pc": pid, "method": method, "path": path, "params": params, "extra": extra_headers})
                    if (extra_headers or {}).get("If-None-Match") == '"v1"':
                        return 304, b"", "image/jpeg", {"etag": '"v1"'}
                    return 200, b"\xff\xd8\xffCOVER", "image/jpeg", {"etag": '"v1"'}
                code, content, ctype = await fake(method, path, params, body, timeout)
                return code, content, ctype, {}

            hub.agent_fetch = fetch

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
    for path in ("/api/gallery", "/api/gallery/thumb?name=a.png", "/api/gallery/file?name=a.png", "/api/jobs/history", "/api/power-plan", "/api/top"):
        assert client.get(path, headers=h).status_code == 200, path
    for method, path in (("GET", "/api/programs"), ("GET", "/api/processes"), ("GET", "/api/screenshot"), ("GET", "/api/clipboard"),
                         ("POST", "/api/programs/comfy/start"), ("POST", "/api/processes/12/kill"), ("POST", "/api/job/a/cancel"),
                         ("POST", "/api/power-plan"), ("DELETE", "/api/power-plan"), ("POST", "/api/action/clipboard_set")):
        assert client.request(method, path, headers=h).status_code == 403, path


def test_top5_is_relayed_with_only_known_parameters(client):
    assert client.get("/api/top?n=5&evil=1&pc=ki-pc", headers=MASTER).status_code == 200
    last = client.calls[-1]
    assert last["pc"] == "ki-pc" and last["path"] == "/api/top" and last["params"] == {"n": "5"}
    assert client.get("/api/top").status_code == 401


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


# ---- Steam (Phase 9.1) ----
def test_steam_reads_are_open_to_view_devices_but_control_is_not(client):
    h = {"Authorization": "Bearer " + view_token(client)}
    for path in ("/api/steam/status", "/api/steam/games?sort=name&q=x", "/api/steam/games/730", "/api/steam/art/730/cover?w=200"):
        assert client.get(path, headers=h).status_code == 200, path
    n = len(client.calls)
    for path in ("/api/steam/games/730/launch", "/api/steam/games/730/stop", "/api/steam/open/exit"):
        assert client.post(path, headers=h).status_code == 403, path
    assert len(client.calls) == n
    assert client.get("/api/steam/games").status_code == 401 and client.post("/api/steam/games/730/launch").status_code == 401


def test_steam_relay_passes_only_known_parameters_and_validates_input(client):
    client.get("/api/steam/games?sort=name&q=fort&evil=1&pc=ki-pc", headers=MASTER)
    assert client.calls[-1]["pc"] == "ki-pc" and client.calls[-1]["params"] == {"sort": "name", "q": "fort"}
    n = len(client.calls)
    assert client.get("/api/steam/art/730/bogus", headers=MASTER).status_code == 400
    assert client.get("/api/steam/art/0/cover", headers=MASTER).status_code == 400
    assert client.post("/api/steam/games/0/launch", headers=MASTER).status_code == 400
    assert client.post("/api/steam/games/99999999999/launch", headers=MASTER).status_code == 400
    assert client.post("/api/steam/open/format-c", headers=MASTER).status_code == 400
    assert len(client.calls) == n                                                                # nichts davon erreichte den Agenten


def test_steam_launch_is_logged_with_name_and_forwards_force(client):
    assert client.post("/api/steam/games/730/launch?pc=ki-pc", headers=MASTER, json={"force": True, "evil": 1}).status_code == 200
    last = client.calls[-1]
    assert last["path"] == "/api/steam/games/730/launch" and last["body"] == {"force": True}
    client.post("/api/steam/games/730/stop", headers=MASTER)
    client.post("/api/steam/open/bigpicture", headers=MASTER)
    raw = json.dumps(client.get("/api/audit", headers=MASTER).json(), ensure_ascii=False)
    for text in ("Spiel gestartet", "Spiel beendet", "Counter-Strike 2 (730)", "Steam: Big Picture"):
        assert text in raw, text


def test_steam_art_is_cacheable_and_supports_etag(client):
    r = client.get("/api/steam/art/730/cover?w=200", headers=MASTER)
    assert r.headers["cache-control"] == "private, max-age=86400" and r.headers["etag"] == '"v1"' and r.content.startswith(b"\xff\xd8\xff")
    r2 = client.get("/api/steam/art/730/cover?w=200", headers={**MASTER, "If-None-Match": '"v1"'})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == '"v1"'
    assert client.calls[-1]["params"] == {"w": "200"}
    assert client.get("/api/steam/status", headers=MASTER).headers["cache-control"] == "no-store"      # alles andere bleibt ungecacht


def test_steam_downloads_is_readable_by_view_devices_and_relayed(client):
    h = {"Authorization": "Bearer " + view_token(client)}
    assert client.get("/api/steam/downloads", headers=h).status_code == 200
    assert client.calls[-1]["path"] == "/api/steam/downloads" and client.calls[-1]["params"] is None
    assert client.get("/api/steam/downloads").status_code == 401
    assert client.get("/api/steam/downloads", headers=MASTER).headers["cache-control"] == "no-store"
