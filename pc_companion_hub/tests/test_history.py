import os

os.environ["HUB_NO_AUTOCREATE"] = "1"

import pytest
from fastapi.testclient import TestClient

from app import history as hist
from app.main import create_app


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(hist, "now", c)
    return c


def snap(util=50, temp=60, power=200, vram_used=4096, vram_total=8192, cpu=10, ram_used=8192, ram_total=16384):
    return {"gpu": {"util_pct": util, "temp_c": temp, "power_w": power, "vram_used_mb": vram_used, "vram_total_mb": vram_total},
            "cpu": {"util_pct": cpu}, "ram": {"used_mb": ram_used, "total_mb": ram_total}}


def test_extract_handles_missing_values():
    assert hist.extract(snap()) == {"gpu": 50, "temp": 60, "power": 200, "vram": 50.0, "cpu": 10, "ram": 50.0}
    e = hist.extract({"gpu": {"util_pct": 5}})
    assert e["gpu"] == 5 and e["temp"] is None and e["vram"] is None and e["ram"] is None
    assert hist.extract({})["gpu"] is None


def test_feed_writes_one_averaged_row_per_interval(tmp_path, clock):
    h = hist.History(tmp_path / "h.db")
    for util, temp in ((20, 60), (40, 75), (60, 70)):       # drei Snapshots innerhalb von 30 s
        h.feed("pc", snap(util=util, temp=temp))
        clock.t += 9
    assert h.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
    clock.t += 5
    h.feed("pc", snap(util=80, temp=65))                      # Intervall voll -> eine Zeile
    row = h.db.execute("SELECT gpu, temp, power FROM samples").fetchall()
    assert len(row) == 1
    assert row[0][0] == pytest.approx(50.0) and row[0][1] == 75 and row[0][2] == 200   # Last gemittelt, Temperatur = Spitze


def test_each_pc_has_its_own_history(tmp_path, clock):
    h = hist.History(tmp_path / "h.db")
    for pc, util in (("a", 10), ("b", 90)):
        h.feed(pc, snap(util=util))
    clock.t += 31
    for pc, util in (("a", 10), ("b", 90)):
        h.feed(pc, snap(util=util))
    assert [p["gpu"] for p in h.query("a", 1)["points"]] == [10]
    assert [p["gpu"] for p in h.query("b", 1)["points"]] == [90]
    assert h.query("unbekannt", 1)["points"] == []


def test_query_buckets_and_limits_points(tmp_path, clock):
    h = hist.History(tmp_path / "h.db")
    for i in range(2 * 2880):                                 # 2 Tage im 30-s-Takt direkt in die DB
        h.db.execute("INSERT INTO samples VALUES ('pc', ?, ?, 60, 100, 50, 10, 40)", [int(clock.t - i * 30), i % 100])
    h.db.commit()
    day = h.query("pc", 24)
    assert len(day["points"]) <= hist.MAX_POINTS + 1 and day["bucket_s"] == 360
    assert day["points"][0]["t"] < day["points"][-1]["t"]
    hour = h.query("pc", 1)
    assert hour["bucket_s"] == hist.SAMPLE_S and 100 <= len(hour["points"]) <= 121
    assert h.query("pc", 9999)["hours"] == hist.RETENTION_S / 3600        # Obergrenze
    assert h.query("pc", 0)["hours"] == 0.25                              # Untergrenze


def test_old_rows_are_purged(tmp_path, clock):
    h = hist.History(tmp_path / "h.db")
    h.db.execute("INSERT INTO samples VALUES ('pc', ?, 1,1,1,1,1,1)", [int(clock.t - hist.RETENTION_S - 100)])
    h.db.commit()
    h.feed("pc", snap())
    clock.t += hist.SAMPLE_S + 1
    h.feed("pc", snap())
    assert h.db.execute("SELECT COUNT(*) FROM samples WHERE t < ?", [int(clock.t - hist.RETENTION_S)]).fetchone()[0] == 0


def test_unusable_database_does_not_break(tmp_path):
    (tmp_path / "h.db").mkdir()                               # ein Ordner statt einer Datei
    h = hist.History(tmp_path / "h.db")
    h.feed("pc", snap())
    assert h.query("pc", 1)["points"] == []


def test_endpoint(tmp_path, clock):
    opts = {"ui_token": "ui", "pcs": [{"name": "A", "host": "h", "token": "t"}, {"name": "B", "host": "h2", "token": "t"}]}
    with TestClient(create_app(opts, data_dir=tmp_path)) as c:
        auth = {"Authorization": "Bearer ui"}
        assert c.get("/api/history").status_code == 401
        h = c.app.state.hubs["b"].on_snapshot                 # Rückruf ist gesetzt
        h("b", snap(util=77)); clock.t += 31; h("b", snap(util=77))
        assert [p["gpu"] for p in c.get("/api/history?pc=b&hours=1", headers=auth).json()["points"]] == [77]
        assert c.get("/api/history?hours=1", headers=auth).json()["points"] == []     # Standard-PC "a" ist leer
        assert c.get("/api/history?pc=x", headers=auth).status_code == 404
