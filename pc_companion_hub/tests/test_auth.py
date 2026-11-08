import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import auth, main
from app.main import create_app

OPTS = {"agent_host": "", "agent_token": "a", "ui_token": "master-token", "pin": "482913", "pc_mac": "",
        "public_url": "https://pi.example.ts.net"}
MASTER = {"Authorization": "Bearer master-token"}


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(auth, "now", c)
    return c


@pytest.fixture()
def client(tmp_path, clock):
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c:
        yield c


def login(client, secret="482913", **extra):
    return client.post("/api/login", json={"secret": secret, **extra})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_pin_login_gives_device_token(client):
    r = login(client, name="Pixel 8")
    assert r.status_code == 200
    token = r.json()["token"]
    assert len(token) >= 40 and r.json()["device"]["name"] == "Pixel 8"
    assert client.get("/api/status", headers=bearer(token)).status_code == 200
    assert "482913" not in r.text


def test_login_accepts_ui_token_too_and_rejects_others(client):
    assert login(client, "master-token").status_code == 200
    assert login(client, "falsch").status_code == 401
    assert login(client, "").status_code == 401
    assert client.post("/api/login", json={}).status_code == 401
    assert client.post("/api/login", json={"secret": 482913}).status_code == 401


def test_master_token_still_works_as_bearer(client):
    assert client.get("/api/status", headers=MASTER).status_code == 200
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers=bearer("irgendwas")).status_code == 401


def test_default_device_name_from_user_agent(client):
    ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36"
    r = client.post("/api/login", json={"secret": "482913"}, headers={"User-Agent": ua})
    assert r.json()["device"]["name"] == "Android (Chrome)"


def test_lockout_after_five_failures_then_release(client, clock):
    for _ in range(5):
        assert login(client, "000000").status_code == 401
    r = login(client, "482913")             # auch die richtige PIN ist jetzt gesperrt
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    clock.t += auth.LOCK_S + 5
    assert login(client, "482913").status_code == 200


def test_success_resets_failure_counter(client):
    for _ in range(4):
        login(client, "000000")
    assert login(client, "482913").status_code == 200
    for _ in range(4):
        assert login(client, "000000").status_code == 401   # Zähler begann von vorn


def test_global_limit_locks_everyone(client, clock, monkeypatch):
    monkeypatch.setattr(auth, "GLOBAL_LIMIT", 6)
    monkeypatch.setattr(auth, "LOCK_AFTER", 100)
    for _ in range(6):
        login(client, "000000")
    assert login(client, "482913").status_code == 429
    clock.t += auth.GLOBAL_LOCK_S + 5
    assert login(client, "482913").status_code == 200


def test_pairing_flow_is_one_time(client):
    r = client.post("/api/pair", headers=MASTER, json={"base": "http://192.168.1.10:8099/"})
    assert r.status_code == 200
    data = r.json()
    assert data["url"] == f"http://192.168.1.10:8099/#pair={data['code']}"
    assert data["qr"].startswith("data:image/svg+xml") and data["expires_s"] == auth.PAIR_TTL_S

    ok = client.post("/api/pair/redeem", json={"code": data["code"], "name": "Tablet"})
    assert ok.status_code == 200 and ok.json()["device"]["name"] == "Tablet"
    assert client.get("/api/status", headers=bearer(ok.json()["token"])).status_code == 200
    assert client.post("/api/pair/redeem", json={"code": data["code"]}).status_code == 401   # nur einmal


def test_pairing_code_expires(client, clock):
    code = client.post("/api/pair", headers=MASTER, json={"base": "https://x.example"}).json()["code"]
    clock.t += auth.PAIR_TTL_S + 1
    assert client.post("/api/pair/redeem", json={"code": code}).status_code == 401


def test_pairing_needs_auth_and_valid_base(client, tmp_path):
    assert client.post("/api/pair", json={"base": "http://x"}).status_code == 401
    r = client.post("/api/pair", headers=MASTER, json={"base": "javascript:alert(1)"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://pi.example.ts.net/#pair=")   # Fallback public_url
    with TestClient(create_app(dict(OPTS, public_url=""), data_dir=tmp_path / "x")) as c2:
        assert c2.post("/api/pair", headers=MASTER, json={"base": "ftp://x"}).status_code == 400
        assert c2.post("/api/pair", headers=MASTER, json={}).status_code == 400


def test_wrong_pair_codes_count_as_failures(client):
    for _ in range(5):
        assert client.post("/api/pair/redeem", json={"code": "geraten"}).status_code == 401
    assert client.post("/api/pair/redeem", json={"code": "nochmal"}).status_code == 429


def test_device_list_revoke_and_websocket(client):
    token = login(client, name="Handy").json()["token"]
    login(client, name="Zweitgerät")
    lst = client.get("/api/devices", headers=bearer(token)).json()
    assert {d["name"] for d in lst["devices"]} == {"Handy", "Zweitgerät"} and lst["current"]
    assert all("hash" not in d and "token" not in d for d in lst["devices"])
    assert client.get("/api/devices", headers=MASTER).json()["current"] is None

    own = lst["current"]
    with client.websocket_connect("/ws?token=" + token) as ws:
        assert ws.receive_json()["pcs"] and ws.receive_json()["status"] == "offline"
        assert client.delete("/api/devices/" + own, headers=MASTER).status_code == 200
    assert client.get("/api/status", headers=bearer(token)).status_code == 401
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=" + token):
            pass
    assert client.delete("/api/devices/" + own, headers=MASTER).status_code == 404
    assert client.delete("/api/devices/abc").status_code == 401


def test_devices_persist_across_restart_and_store_only_hashes(tmp_path, clock):
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c1:
        token = login(c1).json()["token"]
    raw = (tmp_path / "devices.json").read_text(encoding="utf-8")
    assert token not in raw and auth.hash_token(token) in raw
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c2:
        assert c2.get("/api/status", headers=bearer(token)).status_code == 200


def test_device_limit_drops_least_recently_used(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(auth, "MAX_DEVICES", 3)
    store = auth.DeviceStore(tmp_path / "d.json")
    tokens = []
    for i in range(3):
        clock.t += 10
        tokens.append(store.create(f"g{i}")[1])
    clock.t += 100
    store.verify(tokens[0])                  # g0 wurde zuletzt benutzt
    store.create("neu")
    assert {d["name"] for d in store.public()} == {"g0", "g2", "neu"}
    assert store.verify(tokens[1]) is None   # g1 war am längsten ungenutzt


def test_ingress_ip_is_trusted_without_token(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(main, "TRUSTED_PROXY_IPS", {"testclient"})
    with TestClient(create_app(dict(OPTS), data_dir=tmp_path)) as c:
        assert c.get("/api/auth/info").json()["trusted"] is True
        assert c.get("/api/status").status_code == 200
        assert c.get("/api/devices").json()["kind"] == "ingress"
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["pcs"] and ws.receive_json()["status"] == "offline"


def test_direct_access_is_not_trusted(client):
    info = client.get("/api/auth/info").json()
    assert info == {"trusted": False, "pin": True, "pin_numeric": True, "qr": True}


def test_only_ui_token_configured_still_works(tmp_path, clock):
    with TestClient(create_app({"ui_token": "nur-token", "agent_host": ""}, data_dir=tmp_path)) as c:
        assert c.get("/api/auth/info").json()["pin"] is False
        assert login(c, "nur-token").status_code == 200
        assert login(c, "").status_code == 401


def test_nothing_configured_rejects_all(tmp_path, clock):
    with TestClient(create_app({"agent_host": ""}, data_dir=tmp_path)) as c:
        assert login(c, "").status_code == 401
        assert login(c, "irgendwas").status_code == 401
        assert c.get("/api/status", headers=bearer("")).status_code == 401
