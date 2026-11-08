import asyncio
import json
import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import httpx
import pytest
from fastapi.testclient import TestClient

from app import notify
from app.main import create_app


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(notify, "now", c)
    return c


def run(opts, steps):
    """Führt steps(notifier, sent) in einem Event-Loop aus und gibt die gesendeten Nachrichten zurück."""
    sent = []

    async def fake_send(title, message, tag=None):
        sent.append((title, message, tag))
        return True, "ok"

    async def go():
        n = notify.Notifier(opts, fake_send)
        await steps(n)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(go())
    return sent


async def noop():
    await asyncio.sleep(0)


def snap(job=None, temp=60, jobs=None):
    s = {"gpu": {"temp_c": temp}}
    if job:
        s["job"] = job
    if jobs:
        s["jobs"] = jobs
    return s


def job(state, jid="j1", title="Sonnenuntergang", message=None):
    return {"job_id": jid, "tool": "SIG", "state": state, "title": title, "message": message}


def test_job_done_is_reported_once(clock):
    async def steps(n):
        n.on_snapshot("pc", "Gaming-PC", snap(job("running")))
        n.on_snapshot("pc", "Gaming-PC", snap(job("done")))
        n.on_snapshot("pc", "Gaming-PC", snap(job("done")))          # derselbe Job bleibt 2 Min. im Snapshot

    sent = run({}, steps)
    assert len(sent) == 1 and sent[0][0] == "KI-Job fertig" and "Gaming-PC" in sent[0][1] and "Sonnenuntergang" in sent[0][1]


def test_job_error_carries_message(clock):
    async def steps(n):
        n.on_snapshot("pc", "A", snap(job("queued")))
        n.on_snapshot("pc", "A", snap(job("error", message="CUDA out of memory")))

    sent = run({}, steps)
    assert sent[0][0] == "KI-Job fehlgeschlagen" and "CUDA out of memory" in sent[0][1]


def test_old_finished_job_at_startup_is_not_reported(clock):
    async def steps(n):
        n.on_snapshot("pc", "A", snap(job("done")))                  # Hub startet, Job war schon fertig

    assert run({}, steps) == []


def test_jobs_list_and_switch_off(clock):
    async def steps(n):
        n.on_snapshot("pc", "A", snap(jobs=[job("running", "a"), job("running", "b")]))
        n.on_snapshot("pc", "A", snap(jobs=[job("done", "a"), job("running", "b")]))

    assert len(run({}, steps)) == 1
    assert run({"notify_jobs": False}, steps) == []


def test_pc_state_needs_to_be_stable_and_skips_initial(clock):
    async def steps(n):
        n.on_status("pc", "A", "offline"); clock.t += 25; n.on_status("pc", "A", "offline")   # Start: still
        n.on_status("pc", "A", "waking"); clock.t += 5
        n.on_status("pc", "A", "online"); clock.t += 10
        n.on_status("pc", "A", "online")                                  # erst 10 s stabil: noch nichts
        clock.t += 15; n.on_status("pc", "A", "online")                   # 25 s: melden
        n.on_status("pc", "A", "offline"); clock.t += 5
        n.on_status("pc", "A", "online"); clock.t += 25                   # kurzer Aussetzer: nichts
        n.on_status("pc", "A", "online")

    sent = run({}, steps)
    assert [s[0] for s in sent] == ["PC ist online"]


def test_offline_is_reported_and_suppressed_after_hub_shutdown(clock):
    async def steps(n):
        n.on_status("pc", "A", "online"); clock.t += 25; n.on_status("pc", "A", "online")
        n.on_status("pc", "A", "offline"); clock.t += 25; n.on_status("pc", "A", "offline")
        n.on_status("p2", "B", "online"); clock.t += 25; n.on_status("p2", "B", "online")
        n.expect_power_action("p2")
        n.on_status("p2", "B", "offline"); clock.t += 25; n.on_status("p2", "B", "offline")

    sent = run({}, steps)
    assert [(s[0], s[1].split()[0]) for s in sent] == [("PC ist offline", "A")]


def test_hot_gpu_after_a_minute_with_cooldown(clock):
    async def steps(n):
        n.on_snapshot("pc", "A", snap(temp=90)); clock.t += 30
        n.on_snapshot("pc", "A", snap(temp=91)); clock.t += 31        # 61 s heiß -> melden
        n.on_snapshot("pc", "A", snap(temp=92)); clock.t += 600       # Cooldown
        n.on_snapshot("pc", "A", snap(temp=92)); clock.t += 1300      # Cooldown vorbei
        n.on_snapshot("pc", "A", snap(temp=92))

    sent = run({"notify_temp_c": 85}, steps)
    assert [s[0] for s in sent] == ["GPU sehr heiß", "GPU sehr heiß"]


def test_short_temperature_spike_or_disabled_limit_is_silent(clock):
    async def spike(n):
        n.on_snapshot("pc", "A", snap(temp=90)); clock.t += 20
        n.on_snapshot("pc", "A", snap(temp=70)); clock.t += 100       # abgekühlt, Timer zurückgesetzt
        n.on_snapshot("pc", "A", snap(temp=90)); clock.t += 30
        n.on_snapshot("pc", "A", snap(temp=90))

    assert run({"notify_temp_c": 85}, spike) == []
    assert run({"notify_temp_c": 0}, spike) == []


def test_ha_notifier_calls_the_service_through_the_supervisor_proxy():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], request.read().decode()
        return httpx.Response(200, json=[])

    ha = notify.HaNotifier("notify.mobile_app_pixel_8", "sup-token", "http://supervisor/core/api", httpx.MockTransport(handler))
    ok, _ = asyncio.run(ha.send("Titel", "Text", "tag1"))
    assert ok and seen["url"] == "http://supervisor/core/api/services/notify/mobile_app_pixel_8"
    assert seen["auth"] == "Bearer sup-token"
    assert json.loads(seen["body"]) == {"title": "Titel", "message": "Text", "data": {"tag": "tag1"}}


def test_ha_notifier_reports_problems_clearly():
    assert not notify.HaNotifier("", "t").configured and not notify.HaNotifier("kein-dienst", "t").configured
    ok, msg = asyncio.run(notify.HaNotifier("notify.x", None).send("a", "b"))
    assert not ok and "Supervisor-Token" in msg
    ok, msg = asyncio.run(notify.HaNotifier("nix", "t").send("a", "b"))
    assert not ok and "notify_service" in msg
    ha = notify.HaNotifier("notify.x", "t", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    ok, msg = asyncio.run(ha.send("a", "b"))
    assert not ok and "404" in msg and ha.last_error == msg


def test_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    opts = {"ui_token": "ui", "notify_service": "notify.mobile_app_x", "notify_temp_c": 80}
    auth = {"Authorization": "Bearer ui"}
    with TestClient(create_app(opts, data_dir=tmp_path)) as c:
        assert c.get("/api/notify").status_code == 401
        info = c.get("/api/notify", headers=auth).json()
        assert info["configured"] is True and info["service"] == "notify.mobile_app_x" and info["temp_c"] == 80
        assert c.post("/api/notify/test").status_code == 401
    with TestClient(create_app({"ui_token": "ui"}, data_dir=tmp_path)) as c:
        assert c.get("/api/notify", headers=auth).json()["configured"] is False
        r = c.post("/api/notify/test", headers=auth)
        assert r.status_code == 502 and "notify_service" in r.json()["detail"]
