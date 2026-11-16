"""Zeitpläne (Phase 10.5): zeitgesteuerte Aktionen im Hub (der Agent kann nicht planen, wenn der PC aus ist).

Aktionen: ``wake`` (Magic Packet), ``scene`` (Szene ausführen) und ``standby_if_idle`` („Energiesparmodus, wenn nichts läuft“).
Verpasste Läufe (Hub war aus) werden **nicht** nachgeholt: ein Zeitplan löst nur in den ersten Minuten ab der Uhrzeit aus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path

log = logging.getLogger("pc-companion-hub")

SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
MAX_SCHEDULES = 30
LATE_S = 180                       # so spät nach der Uhrzeit darf ein Lauf noch auslösen (Tick-Verzögerung), danach gilt er als verpasst
IDLE_GPU_PCT = 15                  # „nichts läuft“: GPU-Last darunter ...
IDLE_CPU_PCT = 40                  # ... und CPU-Last darunter, kein KI-Job, kein Spiel, keine Szene
TYPES = ("wake", "scene", "standby_if_idle")
IDLE_MODES = ("standby", "sleep", "shutdown")
DAY_NAMES = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class ScheduleError(ValueError):
    """Ungültiger Zeitplan (-> HTTP 400)."""


def resolve_tz(name: str | None) -> tzinfo | None:
    """Zeitzone aus der Option/Umgebung (Europe/Berlin …); ohne Zeitzonendaten die lokale Zeit des Rechners."""
    for candidate in (name, os.environ.get("TZ")):
        if candidate:
            try:
                from zoneinfo import ZoneInfo
                return ZoneInfo(candidate)
            except Exception:                                      # noqa: BLE001 - unbekannte Zone oder fehlende tzdata
                continue
    return None


def _int(v, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ScheduleError(f"{what} muss eine ganze Zahl von {lo} bis {hi} sein")
    return v


def clean_schedule(raw, sid: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ScheduleError("ungültiger Zeitplan")
    name = "".join(c for c in str(raw.get("name") or "") if c.isprintable()).strip()[:40]
    if not name:
        raise ScheduleError("Name fehlt")
    days = raw.get("days")
    if not isinstance(days, list) or not days or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise ScheduleError("Mindestens ein Wochentag (0 = Montag bis 6 = Sonntag)")
    t = raw.get("time")
    if not isinstance(t, str) or not TIME_RE.fullmatch(t):
        raise ScheduleError("Uhrzeit muss HH:MM sein")
    act = raw.get("action")
    if not isinstance(act, dict) or act.get("type") not in TYPES:
        raise ScheduleError("Unbekannte Aktion")
    action: dict = {"type": act["type"]}
    if act["type"] == "scene":
        scene_id = act.get("scene_id")
        if not isinstance(scene_id, str) or not SAFE_ID.fullmatch(scene_id):
            raise ScheduleError("Szene fehlt")
        action["scene_id"] = scene_id
    elif act["type"] == "standby_if_idle":
        action["idle_minutes"] = _int(act.get("idle_minutes", 10), 1, 120, "Ruhezeit")
        action["window_minutes"] = _int(act.get("window_minutes", 120), 10, 720, "Zeitfenster")
        action["mode"] = act.get("mode", "standby")
        if action["mode"] not in IDLE_MODES:
            raise ScheduleError("mode muss standby, sleep oder shutdown sein")
    out = {"id": sid or (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "plan") + "-" + secrets.token_hex(3), "name": name,
           "enabled": raw.get("enabled", True) is not False, "days": sorted(set(days)), "time": t, "action": action}
    pc = raw.get("pc")
    if pc:
        if not isinstance(pc, str) or not SAFE_ID.fullmatch(pc):
            raise ScheduleError("PC ungültig")
        out["pc"] = pc
    return out


def is_critical(s: dict) -> bool:
    """Ein Zeitplan, der den PC ausschaltet (Energiesparmodus/Ruhezustand/Herunterfahren) – wird nur mit der Sicherheits-PIN angelegt."""
    return s["action"]["type"] == "standby_if_idle"


def describe(s: dict) -> str:
    days = s["days"]
    d = "täglich" if days == list(range(7)) else ("Mo–Fr" if days == list(range(5)) else "Sa, So" if days == [5, 6] else ", ".join(DAY_NAMES[i] for i in days))
    a = s["action"]
    what = "PC aufwecken" if a["type"] == "wake" else ("Szene ausführen" if a["type"] == "scene" else "Energiesparmodus, wenn nichts läuft")
    return f"{d} um {s['time']}: {what}"


class ScheduleStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._items: list[dict] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in data.get("schedules", []) if isinstance(data, dict) else []:
                try:
                    item = clean_schedule(raw, raw.get("id") if isinstance(raw, dict) and SAFE_ID.fullmatch(str(raw.get("id", ""))) else None)
                except ScheduleError:
                    continue
                for k in ("last_run", "skip_date"):                    # Zustand bleibt über einen Neustart erhalten
                    if isinstance(raw.get(k), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw[k]):
                        item[k] = raw[k]
                self._items.append(item)
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schedules": self._items}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return [dict(s) for s in self._items]

    def get(self, sid: str) -> dict | None:
        return next((dict(s) for s in self._items if s["id"] == sid), None)

    def create(self, raw) -> dict:
        if len(self._items) >= MAX_SCHEDULES:
            raise ScheduleError(f"Höchstens {MAX_SCHEDULES} Zeitpläne")
        item = clean_schedule(raw)
        self._items.append(item)
        self._save()
        return dict(item)

    def replace(self, sid: str, raw) -> dict | None:
        for i, s in enumerate(self._items):
            if s["id"] == sid:
                item = clean_schedule(raw, sid)
                self._items[i] = item                                    # eine Änderung setzt „übersprungen“ und „zuletzt gelaufen“ zurück
                self._save()
                return dict(item)
        return None

    def delete(self, sid: str) -> bool:
        n = len(self._items)
        self._items = [s for s in self._items if s["id"] != sid]
        if len(self._items) != n:
            self._save()
        return len(self._items) != n

    def mark(self, sid: str, **fields) -> None:
        for s in self._items:
            if s["id"] == sid:
                for k, v in fields.items():
                    if v is None:
                        s.pop(k, None)
                    else:
                        s[k] = v
                self._save()
                return


def next_run_date(s: dict, now: datetime) -> date:
    """Datum des nächsten Laufs (heute, wenn die Uhrzeit noch nicht vorbei ist)."""
    hh, mm = (int(x) for x in s["time"].split(":"))
    for add in range(8):
        d = (now + timedelta(days=add)).date()
        at = now.replace(year=d.year, month=d.month, day=d.day, hour=hh, minute=mm, second=0, microsecond=0)
        if d.weekday() in s["days"] and at + timedelta(seconds=LATE_S) > now:
            return d
    return now.date()


class Scheduler:
    """Prüft die Zeitpläne in kurzen Abständen und löst fällige aus. Alle Abhängigkeiten werden übergeben, damit der Ablauf ohne Uhr und Netz testbar ist."""

    def __init__(self, store: ScheduleStore, hubs: dict, scene_store, scene_runner, audit, send_wake, now, spawn=None, sleep=asyncio.sleep):
        self.store, self.hubs, self.scene_store, self.runner, self.audit, self.send_wake = store, hubs, scene_store, scene_runner, audit, send_wake
        self.now, self.sleep = now, sleep
        self.spawn = spawn or (lambda coro: asyncio.get_running_loop().create_task(coro))
        self.watch: dict[str, dict] = {}                     # laufende „Energiesparmodus, wenn nichts läuft“-Beobachtungen

    def hub_for(self, s: dict):
        pc = s.get("pc")
        return self.hubs.get(pc) if pc else next(iter(self.hubs.values()))

    def skip_next(self, sid: str) -> str | None:
        s = self.store.get(sid)
        if not s:
            return None
        d = next_run_date(s, self.now()).isoformat()
        self.store.mark(sid, skip_date=d)
        return d

    def unskip(self, sid: str) -> None:
        self.store.mark(sid, skip_date=None)

    async def tick(self) -> None:
        now = self.now()
        today = now.date().isoformat()
        for s in self.store.list():
            if not s["enabled"] or now.weekday() not in s["days"] or s.get("last_run") == today:
                continue
            hh, mm = (int(x) for x in s["time"].split(":"))
            late = (now - now.replace(hour=hh, minute=mm, second=0, microsecond=0)).total_seconds()
            if not 0 <= late < LATE_S:
                continue
            self.store.mark(s["id"], last_run=today)
            if s.get("skip_date") == today:
                self.store.mark(s["id"], skip_date=None)
                self.audit.add("Zeitplan", "Zeitplan übersprungen", None, f"{s['name']} (heute nicht)")
                continue
            await self._fire(s, now)
        for sid in list(self.watch):
            await self._watch(sid, now)

    async def _fire(self, s: dict, now: datetime) -> None:
        hub, a = self.hub_for(s), s["action"]
        pc = (hub.name or hub.pc_id) if hub else None
        if hub is None:
            self.audit.add("Zeitplan", "Zeitplan fehlgeschlagen", None, f"{s['name']}: PC nicht eingerichtet", False)
            return
        if a["type"] == "wake":
            if hub.status == "online":
                self.audit.add("Zeitplan", "Zeitplan: PC war schon online", pc, s["name"])
                return
            try:
                self.send_wake(hub)
                self.audit.add("Zeitplan", "Zeitplan: PC aufgeweckt", pc, s["name"])
            except Exception as e:                                  # noqa: BLE001 - z. B. keine MAC-Adresse
                self.audit.add("Zeitplan", "Zeitplan fehlgeschlagen", pc, f"{s['name']}: {getattr(e, 'detail', None) or e.__class__.__name__}", False)
        elif a["type"] == "scene":
            scene = self.scene_store.get(a["scene_id"])
            if not scene:
                self.audit.add("Zeitplan", "Zeitplan fehlgeschlagen", pc, f"{s['name']}: Szene existiert nicht mehr", False)
                return
            if scene.get("pc") and scene["pc"] in self.hubs:
                hub = self.hubs[scene["pc"]]
            try:
                self.runner.start(hub, scene, "Zeitplan")
            except Exception as e:                                  # noqa: BLE001 - es läuft schon eine Szene
                self.audit.add("Zeitplan", "Zeitplan fehlgeschlagen", pc, f"{s['name']}: {e}", False)
                return
            self.audit.add("Zeitplan", "Zeitplan: Szene gestartet", pc, f"{s['name']} → {scene['name']}")
            self.spawn(self.runner.run(hub, scene, "Zeitplan"))
        else:
            self.watch[s["id"]] = {"since": now.timestamp(), "idle_since": None}
            self.audit.add("Zeitplan", "Zeitplan: wartet auf Ruhe", pc, f"{s['name']} (bis zu {a['window_minutes']} Min.)")

    @staticmethod
    def is_idle(hub) -> bool:
        snap = hub.snapshot or {}
        gpu, cpu = snap.get("gpu") or {}, snap.get("cpu") or {}
        jobs = snap.get("jobs") or ([snap["job"]] if snap.get("job") else [])
        if any(j.get("state") in ("queued", "running") for j in jobs):
            return False
        if (snap.get("steam") or {}).get("running") or (hub.scene_run and hub.scene_run.get("state") == "running"):
            return False
        return (gpu.get("util_pct") or 0) < IDLE_GPU_PCT and (cpu.get("util_pct") or 0) < IDLE_CPU_PCT

    async def _watch(self, sid: str, now: datetime) -> None:
        w, s = self.watch[sid], self.store.get(sid)
        if not s:
            self.watch.pop(sid, None)
            return
        hub, a, t = self.hub_for(s), s["action"], now.timestamp()
        pc = (hub.name or hub.pc_id) if hub else None
        if hub is None or hub.status != "online":
            self.watch.pop(sid, None)
            self.audit.add("Zeitplan", "Zeitplan: nichts zu tun", pc, f"{s['name']}: PC ist schon aus")
            return
        if self.is_idle(hub):
            w["idle_since"] = w["idle_since"] or t
            if t - w["idle_since"] >= a["idle_minutes"] * 60:
                self.watch.pop(sid, None)
                code, data = await hub.agent_action(a["mode"], None)
                ok = code < 300
                self.audit.add("Zeitplan", "Zeitplan: PC ausgeschaltet" if ok else "Zeitplan fehlgeschlagen", pc,
                               f"{s['name']} ({a['mode']})" + ("" if ok else f": {(data or {}).get('detail') or code}"), ok)
                return
        else:
            w["idle_since"] = None
        if t - w["since"] >= a["window_minutes"] * 60:
            self.watch.pop(sid, None)
            self.audit.add("Zeitplan", "Zeitplan: übersprungen", pc, f"{s['name']}: der PC war {a['window_minutes']} Min. lang beschäftigt")

    async def run(self, every_s: float = 15.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception:                                      # noqa: BLE001 - der Planer darf nie sterben
                log.exception("Zeitplan-Prüfung fehlgeschlagen")
            await self.sleep(every_s)
