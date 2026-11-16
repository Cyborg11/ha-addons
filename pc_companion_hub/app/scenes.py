"""Szenen (Phase 10.2): benannte Abfolgen aus festen Schritten, z. B. „Zocken“ = ComfyUI beenden -> Spiel starten -> Home-Assistant-Szene.

Gespeichert und ausgeführt wird im Hub (der Agent kann keine Abfolgen über einen Ausfall des PCs hinweg). Die Schritt-Typen sind eine feste
Liste mit geprüften Parametern – keine freien Befehle. Jeder Schritt nutzt die vorhandenen, geschützten Agent-Endpunkte.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path

SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
SCENE_ENTITY = re.compile(r"scene\.[a-z0-9_]{1,64}")
MAX_SCENES = 20
MAX_STEPS = 30
MAX_WAIT_S = 300
# Aktionen des Agenten, die eine Szene auslösen darf (ohne Neustart des Agenten, Zwischenablage und freie URLs)
SCENE_ACTIONS = ("lock", "sleep", "standby", "shutdown", "restart", "monitor_off", "mute", "volume", "media_play_pause", "media_next", "media_prev")
POWER_MODES = ("shutdown", "sleep", "standby")
STEP_TYPES = ("program_start", "program_stop", "game_launch", "game_stop", "action", "power_plan", "ha_scene", "wait", "notify")


class SceneError(ValueError):
    """Ungültige Szene (-> HTTP 400)."""


def _text(v, limit: int, what: str, required: bool = False) -> str:
    if v is None or v == "":
        if required:
            raise SceneError(f"{what} fehlt")
        return ""
    if not isinstance(v, str):
        raise SceneError(f"{what} muss Text sein")
    v = "".join(c for c in v if c.isprintable()).strip()
    if required and not v:
        raise SceneError(f"{what} fehlt")
    return v[:limit]


def _int(v, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise SceneError(f"{what} muss eine ganze Zahl von {lo} bis {hi} sein")
    return v


def clean_step(raw) -> dict:
    """Prüft einen Schritt und gibt nur bekannte Felder zurück."""
    if not isinstance(raw, dict) or raw.get("type") not in STEP_TYPES:
        raise SceneError("unbekannter Schritt-Typ")
    t = raw["type"]
    step: dict = {"type": t}
    if t in ("program_start", "program_stop"):
        pid = raw.get("id")
        if not isinstance(pid, str) or not SAFE_ID.fullmatch(pid):
            raise SceneError("Programm-ID ungültig")
        step["id"] = pid
        step["name"] = _text(raw.get("name"), 60, "Name")
    elif t in ("game_launch", "game_stop"):
        step["appid"] = _int(raw.get("appid"), 1, 2 ** 32 - 1, "AppID")
        step["name"] = _text(raw.get("name"), 80, "Name")
        if t == "game_launch" and raw.get("force") is True:
            step["force"] = True
    elif t == "action":
        name = raw.get("name")
        if name not in SCENE_ACTIONS:
            raise SceneError("Aktion nicht erlaubt")
        step["name"] = name
        if name == "volume":
            step["level"] = _int(raw.get("level"), 0, 100, "Lautstärke")
    elif t == "power_plan":
        if raw.get("cancel") is True:
            step["cancel"] = True
        else:
            if raw.get("after_job") is not None:
                if raw["after_job"] not in POWER_MODES:
                    raise SceneError("after_job muss shutdown, sleep oder standby sein")
                step["after_job"] = raw["after_job"]
            if raw.get("timer_minutes") is not None:
                step["timer_minutes"] = _int(raw["timer_minutes"], 1, 1440, "Timer")
                step["mode"] = raw.get("mode", "shutdown")
                if step["mode"] not in POWER_MODES:
                    raise SceneError("mode muss shutdown, sleep oder standby sein")
            if "after_job" not in step and "timer_minutes" not in step:
                raise SceneError("Energie-Plan braucht after_job, timer_minutes oder cancel")
    elif t == "ha_scene":
        ent = raw.get("entity_id")
        if not isinstance(ent, str) or not SCENE_ENTITY.fullmatch(ent):
            raise SceneError("Home-Assistant-Szene muss scene.<name> heißen")
        step["entity_id"] = ent
    elif t == "wait":
        step["seconds"] = _int(raw.get("seconds"), 1, MAX_WAIT_S, "Wartezeit")
    elif t == "notify":
        step["message"] = _text(raw.get("message"), 200, "Nachricht", required=True)
    return step


def clean_scene(raw, scene_id: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SceneError("ungültige Szene")
    name = _text(raw.get("name"), 40, "Name", required=True)
    steps = raw.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise SceneError(f"Eine Szene braucht 1 bis {MAX_STEPS} Schritte")
    out = {"id": scene_id or _new_id(name), "name": name, "icon": _text(raw.get("icon"), 4, "Symbol"),
           "wake": raw.get("wake", True) is not False, "steps": [clean_step(s) for s in steps]}
    pc = raw.get("pc")
    if pc:
        if not isinstance(pc, str) or not SAFE_ID.fullmatch(pc):
            raise SceneError("PC ungültig")
        out["pc"] = pc
    return out


def _new_id(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "szene") + "-" + secrets.token_hex(3)


def is_critical(scene: dict) -> bool:
    """Szene mit Schritten, die ohne Rückfrage Schaden anrichten können (Aus-/Ruhezustand/Neustart, Programme oder Spiele beenden): braucht die Sicherheits-PIN."""
    return any(s["type"] in ("program_stop", "game_stop") or (s["type"] == "action" and s["name"] in ("shutdown", "restart", "sleep", "standby"))
               or (s["type"] == "power_plan" and not s.get("cancel")) for s in scene["steps"])


def step_label(s: dict) -> str:
    t = s["type"]
    if t == "program_start":
        return "Programm starten: " + (s.get("name") or s["id"])
    if t == "program_stop":
        return "Programm beenden: " + (s.get("name") or s["id"])
    if t == "game_launch":
        return "Spiel starten: " + (s.get("name") or str(s["appid"]))
    if t == "game_stop":
        return "Spiel beenden: " + (s.get("name") or str(s["appid"]))
    if t == "action":
        return "Aktion: " + s["name"] + (f" ({s['level']} %)" if "level" in s else "")
    if t == "power_plan":
        return "Energie-Plan aufheben" if s.get("cancel") else ("Nach dem letzten Job: " + s["after_job"] if "after_job" in s else f"Timer {s['timer_minutes']} Min.: {s['mode']}")
    if t == "ha_scene":
        return "Home Assistant: " + s["entity_id"]
    if t == "wait":
        return f"Warten {s['seconds']} s"
    return "Nachricht senden"


class SceneStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._scenes: list[dict] = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for raw in data.get("scenes", []) if isinstance(data, dict) else []:
                try:
                    self._scenes.append(clean_scene(raw, raw.get("id") if isinstance(raw, dict) and SAFE_ID.fullmatch(str(raw.get("id", ""))) else None))
                except SceneError:
                    continue                                   # kaputte Einträge überspringen, nie am Start scheitern
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"scenes": self._scenes}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return [dict(s) for s in self._scenes]

    def get(self, sid: str) -> dict | None:
        return next((dict(s) for s in self._scenes if s["id"] == sid), None)

    def create(self, raw) -> dict:
        if len(self._scenes) >= MAX_SCENES:
            raise SceneError(f"Höchstens {MAX_SCENES} Szenen")
        scene = clean_scene(raw)
        self._scenes.append(scene)
        self._save()
        return dict(scene)

    def replace(self, sid: str, raw) -> dict | None:
        for i, s in enumerate(self._scenes):
            if s["id"] == sid:
                self._scenes[i] = clean_scene(raw, sid)
                self._save()
                return dict(self._scenes[i])
        return None

    def delete(self, sid: str) -> bool:
        n = len(self._scenes)
        self._scenes = [s for s in self._scenes if s["id"] != sid]
        if len(self._scenes) != n:
            self._save()
        return len(self._scenes) != n

    def move(self, order: list[str]) -> None:
        by = {s["id"]: s for s in self._scenes}
        self._scenes = [by[i] for i in order if i in by] + [s for s in self._scenes if s["id"] not in order]
        self._save()


def public_run(run: dict | None) -> dict | None:
    if not run:
        return None
    return {k: run[k] for k in ("id", "name", "state", "step", "steps", "started", "ended", "error")}


class SceneRunner:
    """Führt eine Szene Schritt für Schritt aus und hält den Fortschritt in ``hub.scene_run`` (geht über die normale Statusmeldung an die Oberfläche)."""

    def __init__(self, ha, audit, send_wake, sleep=asyncio.sleep, clock=time.time):
        self.ha, self.audit, self.send_wake, self.sleep, self.clock = ha, audit, send_wake, sleep, clock

    @staticmethod
    def running(hub) -> bool:
        return bool(hub.scene_run and hub.scene_run["state"] == "running")

    def start(self, hub, scene: dict, who: str) -> dict:
        if self.running(hub):
            raise SceneError("Auf diesem PC läuft schon eine Szene")
        steps = [{"label": step_label(s), "state": "pending", "error": None} for s in scene["steps"]]
        hub.scene_run = {"id": scene["id"], "name": scene["name"], "state": "running", "step": 0, "steps": steps, "started": self.clock(), "ended": None,
                         "error": None, "cancel": False}
        return hub.scene_run

    async def cancel(self, hub) -> bool:
        if not self.running(hub):
            return False
        hub.scene_run["cancel"] = True
        return True

    async def run(self, hub, scene: dict, who: str = "Szene") -> None:
        run = hub.scene_run
        pc = hub.name or hub.pc_id
        self.audit.add(who, "Szene gestartet", pc, scene["name"])
        off = 0                                                       # Versatz der Szenen-Schritte in run["steps"] (+1 mit „PC aufwecken“)
        try:
            if hub.status != "online":
                await self._wake(hub, scene, run)
                off = 1
            for i, step in enumerate(scene["steps"]):
                if run["cancel"]:
                    self._finish(run, "cancelled", "abgebrochen")
                    break
                run["step"] = i + off
                run["steps"][i + off]["state"] = "running"
                await hub.broadcast()
                ok, msg = await self._step(hub, step, run)
                run["steps"][i + off].update(state="ok" if ok else "error", error=None if ok else msg)
                if not ok:
                    self._finish(run, "error", f"Schritt {i + 1} ({run['steps'][i + off]['label']}): {msg}")
                    break
            else:
                run["state"], run["ended"] = "ok", self.clock()
        except _Fail as e:
            self._finish(run, "cancelled" if str(e) == "abgebrochen" else "error", str(e))
        except Exception as e:                                       # noqa: BLE001 - eine Szene darf nie den Hub mitreißen
            self._finish(run, "error", f"Unerwarteter Fehler: {e.__class__.__name__}")
        ok = run["state"] == "ok"
        what = "Szene beendet" if ok else ("Szene abgebrochen" if run["state"] == "cancelled" else "Szene fehlgeschlagen")
        self.audit.add(who, what, pc, (scene["name"] + ("" if ok else ": " + str(run["error"])))[:240], ok or run["state"] == "cancelled")
        await hub.broadcast()

    def _finish(self, run: dict, state: str, error: str) -> None:
        run["state"], run["error"], run["ended"] = state, error, self.clock()
        for st in run["steps"]:
            if st["state"] == "pending":
                st["state"] = "skipped"
            elif st["state"] == "running":
                st["state"] = "error" if state == "error" else "skipped"

    async def _wake(self, hub, scene: dict, run: dict) -> None:
        """PC ist aus: Magic Packet senden und auf den Agenten warten (Wartezeit und Pause nach „online“ wie bei „Aufwecken und starten“)."""
        if not scene.get("wake", True):
            raise _Fail("PC ist nicht online")
        run["steps"].insert(0, {"label": "PC aufwecken", "state": "running", "error": None})
        await hub.broadcast()
        if hub.status == "offline":
            try:
                self.send_wake(hub)
            except Exception as e:                                   # noqa: BLE001 - z. B. keine MAC-Adresse konfiguriert (HTTPException)
                run["steps"][0].update(state="error", error=str(getattr(e, "detail", None) or e.__class__.__name__))
                raise _Fail(run["steps"][0]["error"])
        deadline = self.clock() + hub.launch_expiry
        online_since = None
        needs_steam = any(s["type"].startswith("game") for s in scene["steps"])
        while self.clock() < deadline:
            if run["cancel"]:
                raise _Fail("abgebrochen")
            if hub.status == "online":
                online_since = online_since or self.clock()
                if self.clock() - online_since >= hub.launch_delay and ("steam" in hub.features or not needs_steam):
                    break
            else:
                online_since = None
            await self.sleep(1.0)
        else:
            run["steps"][0].update(state="error", error="keine Antwort")
            raise _Fail("Der PC hat sich nicht rechtzeitig gemeldet")
        run["steps"][0]["state"] = "ok"

    async def _call(self, hub, method: str, path: str, body=None, timeout: float = 25.0) -> tuple[bool, str, int]:
        code, content, _ = await hub.agent_request(method, path, None, body, timeout)
        if code < 300:
            return True, "", code
        try:
            detail = json.loads(content).get("detail")
        except Exception:                                          # noqa: BLE001
            detail = None
        return False, str(detail or f"Fehler {code}")[:160], code

    async def _step(self, hub, s: dict, run: dict) -> tuple[bool, str]:
        t = s["type"]
        try:
            if t in ("program_start", "program_stop"):
                ok, msg, _ = await self._call(hub, "POST", f"/api/programs/{s['id']}/{'start' if t == 'program_start' else 'stop'}")
                return ok, msg
            if t == "game_launch":
                ok, msg, _ = await self._call(hub, "POST", f"/api/steam/games/{s['appid']}/launch", {"force": bool(s.get("force"))}, 30.0)
                return ok, msg
            if t == "game_stop":
                ok, msg, code = await self._call(hub, "POST", f"/api/steam/games/{s['appid']}/stop", None, 30.0)
                return (ok or code == 409), "" if ok or code == 409 else msg          # läuft nicht: nichts zu beenden, kein Fehler
            if t == "action":
                code, data = await hub.agent_action(s["name"], {"level": s["level"]} if s["name"] == "volume" else None)
                return code < 300, "" if code < 300 else str((data or {}).get("detail") or f"Fehler {code}")[:160]
            if t == "power_plan":
                if s.get("cancel"):
                    ok, msg, _ = await self._call(hub, "DELETE", "/api/power-plan?which=all")
                else:
                    body = {k: s[k] for k in ("after_job", "timer_minutes", "mode") if k in s}
                    ok, msg, _ = await self._call(hub, "POST", "/api/power-plan", body)
                return ok, msg
            if t == "ha_scene":
                return await self.ha.activate_scene(s["entity_id"])
            if t == "wait":
                end = self.clock() + s["seconds"]
                while self.clock() < end:
                    if run["cancel"]:
                        raise _Fail("abgebrochen")                        # mitten im Warten: die Szene endet als „abgebrochen“, nicht als „ok“
                    await self.sleep(min(1.0, end - self.clock()))
                return True, ""
            if t == "notify":
                ok, msg = await self.ha.send("PC-Companion", s["message"], "pcc-scene")
                return ok, "" if ok else msg
        except _Fail:
            raise
        return False, "unbekannter Schritt"


class _Fail(Exception):
    pass
