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


# ---- Benachrichtigungen mit Aktionen (Phase 10.3) ----
BASE = "https://pc.example.org"


def run_actions(opts, steps):
    """Wie run(), aber die Test-Sendefunktion nimmt Aktionen entgegen."""
    sent = []

    async def fake_send(title, message, tag=None, actions=None):
        sent.append((title, message, tag, actions))
        return True, "ok"

    async def go():
        n = notify.Notifier(opts, fake_send)
        await steps(n)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(go())
    return sent


def test_clean_public_url_accepts_only_plain_http_addresses():
    assert notify.clean_public_url(" https://pc.example.org/ ") == BASE and notify.clean_public_url("http://192.168.1.5:8099/#x") == "http://192.168.1.5:8099"
    for bad in (None, "", 5, "javascript:alert(1)", "ftp://x", "https://a b", 'https://x"><script>', "pc.example.org"):
        assert notify.clean_public_url(bad) is None


def test_without_public_url_messages_stay_plain_text_with_the_old_call(clock):
    async def steps(n):
        n.on_snapshot("pc", "A", snap(job("running")))
        n.on_snapshot("pc", "A", snap(job("done")))

    sent = run({}, steps)                                              # run() benutzt eine Sendefunktion OHNE Aktionsparameter: darf nicht brechen
    assert len(sent) == 1 and sent[0][0] == "KI-Job fertig"


def test_job_done_gets_standby_and_gallery_buttons_with_deep_links(clock):
    async def steps(n):
        n.on_snapshot("gaming-pc", "Gaming-PC", snap(job("running")))
        n.on_snapshot("gaming-pc", "Gaming-PC", snap(job("done")))

    sent = run_actions({"public_url": BASE + "/"}, steps)
    assert len(sent) == 1 and sent[0][0] == "KI-Job fertig"
    assert sent[0][3] == [{"action": "URI", "title": "Energiesparmodus", "uri": BASE + "/#do=standby&pc=gaming-pc"},
                          {"action": "URI", "title": "Galerie", "uri": BASE + "/#do=tab:gallery&pc=gaming-pc"}]


def test_offline_and_online_and_error_buttons(clock):
    async def steps(n):
        n.on_status("pc", "A", "online"); clock.t += 25; n.on_status("pc", "A", "online")
        n.on_status("pc", "A", "offline"); clock.t += 25; n.on_status("pc", "A", "offline")
        n.on_status("pc", "A", "online"); clock.t += 25; n.on_status("pc", "A", "online")
        n.on_snapshot("pc", "A", snap(job("running")))
        n.on_snapshot("pc", "A", snap(job("error", message="kaputt")))

    sent = run_actions({"public_url": BASE}, steps)
    by = {s[0]: [a["title"] + "=" + a["uri"].split("#do=")[1] for a in s[3]] for s in sent}
    assert by["PC ist offline"] == ["Aufwecken=wake&pc=pc"] and by["PC ist online"] == ["Dashboard=tab:dash&pc=pc"]
    assert by["KI-Job fehlgeschlagen"] == ["Dashboard=tab:dash&pc=pc"]


def test_hot_gpu_offers_to_cancel_the_running_job_only_when_one_runs(clock):
    async def hot(n, with_job):
        if with_job:
            n.on_snapshot("pc", "A", snap(job("running", jid="job-7"), temp=90))
        n.on_snapshot("pc", "A", snap(temp=90)); clock.t += 70
        n.on_snapshot("pc", "A", snap(temp=90))

    async def with_job(n):
        await hot(n, True)

    async def without(n):
        await hot(n, False)

    a = run_actions({"public_url": BASE}, with_job)
    assert [x["title"] for x in a[0][3]] == ["Job abbrechen", "Dashboard"] and a[0][3][0]["uri"].endswith("#do=cancel-job:job-7&pc=pc")
    clock.t += 10_000
    b = run_actions({"public_url": BASE}, without)
    assert [x["title"] for x in b[0][3]] == ["Dashboard"]


def test_links_are_escaped_and_never_exceed_three_buttons(clock):
    n = notify.Notifier({"public_url": BASE}, None)
    link = n.link("pc/../x y", "tab:dash")
    assert link == BASE + "/#do=tab:dash&pc=pc%2F..%2Fx%20y"
    assert " " not in link and "<" not in link and link.count("#") == 1
    acts = n._actions("pc", [("a", "x"), ("b", "y"), ("c", "z"), ("d", "w")])
    assert len(acts) == notify.MAX_ACTIONS == 3
    assert notify.Notifier({}, None)._actions("pc", [("a", "x")]) is None


def test_ha_notifier_sends_actions_and_click_target():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json=[])

    ha = notify.HaNotifier("notify.mobile_app_x", "tok", "http://supervisor/core/api", httpx.MockTransport(handler))
    acts = [{"action": "URI", "title": "Aufwecken", "uri": BASE + "/#do=wake&pc=pc"}]
    assert asyncio.run(ha.send("PC ist offline", "A", "t1", acts))[0] is True
    data = seen["body"]["data"]
    assert data["tag"] == "t1" and data["actions"] == acts and data["url"] == BASE + "/" and data["clickAction"] == BASE + "/"
    assert asyncio.run(ha.send("x", "y", "t2"))[0] is True and seen["body"]["data"] == {"tag": "t2"}      # ohne Aktionen wie bisher


def test_unconfigured_notify_service_accepts_actions(tmp_path):
    import asyncio
    from app import main as hub_main
    assert asyncio.run(hub_main._no_send("t", "m", "tag", [{"action": "URI"}]))[0] is False
