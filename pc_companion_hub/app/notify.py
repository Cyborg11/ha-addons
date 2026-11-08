"""Benachrichtigungen aufs Handy über Home Assistant (notify-Dienst der Companion-App)."""
from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

log = logging.getLogger("pc-companion-hub")

STABLE_S = 20              # Zustand muss so lange gelten, bevor „online/offline“ gemeldet wird
EXPECT_OFF_S = 600         # nach Herunterfahren/Ruhezustand über den Hub keine „offline“-Meldung
HOT_AFTER_S = 60           # GPU muss so lange zu heiß sein
HOT_COOLDOWN_S = 1800
HOT_HYSTERESIS = 3         # unter Grenze minus 3 °C gilt als abgekühlt
SERVICE_RE = re.compile(r"([a-z_]+)\.([a-z0-9_]+)")


def now() -> float:
    return time.time()


class HaNotifier:
    """Ruft notify.<dienst> über den Supervisor-Proxy der Home-Assistant-API auf."""

    def __init__(self, service: str, token: str | None, base: str = "http://supervisor/core/api", transport=None):
        self.service = (service or "").strip()
        self.token = token
        self.base = base.rstrip("/")
        self.transport = transport
        self.last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(SERVICE_RE.fullmatch(self.service))

    async def send(self, title: str, message: str, tag: str | None = None) -> tuple[bool, str]:
        m = SERVICE_RE.fullmatch(self.service)
        if not m:
            return False, "notify_service ist nicht gesetzt oder ungültig (Beispiel: notify.mobile_app_pixel_8)"
        if not self.token:
            return False, "Kein Supervisor-Token – die Home-Assistant-API ist nur im laufenden Add-on erreichbar"
        payload = {"title": title, "message": message}
        if tag:
            payload["data"] = {"tag": tag}
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self.transport) as client:
                r = await client.post(f"{self.base}/services/{m.group(1)}/{m.group(2)}", json=payload,
                                      headers={"Authorization": f"Bearer {self.token}"})
        except Exception as e:
            self.last_error = f"Home Assistant nicht erreichbar: {e.__class__.__name__}"
            return False, self.last_error
        if r.status_code >= 300:
            self.last_error = f"Home Assistant antwortete {r.status_code} (Dienst {self.service} vorhanden?)"
            return False, self.last_error
        self.last_error = None
        return True, "gesendet"


class Notifier:
    """Erkennt Ereignisse (Job fertig, PC online/offline, GPU zu heiß) und löst Nachrichten aus."""

    def __init__(self, opts: dict, send):
        self.jobs = opts.get("notify_jobs", True) is not False
        self.pc_state = opts.get("notify_pc_state", True) is not False
        self.temp_limit = int(opts.get("notify_temp_c", 85) or 0)
        self.send = send                      # async (title, message, tag)
        self.recs: dict[str, dict] = {}

    def _rec(self, pc: str) -> dict:
        return self.recs.setdefault(pc, {"cur": None, "since": 0.0, "announced": None, "jobs": {}, "hot_since": None,
                                          "last_hot": 0.0, "expect_off": 0.0})

    def _fire(self, title: str, message: str, tag: str) -> None:
        try:
            asyncio.get_running_loop().create_task(self.send(title, message, tag))
        except RuntimeError:
            pass                              # kein Event-Loop (z. B. in Tests ohne Loop)

    def expect_power_action(self, pc: str) -> None:
        self._rec(pc)["expect_off"] = now() + EXPECT_OFF_S

    def on_status(self, pc: str, name: str, status: str) -> None:
        if not self.pc_state:
            return
        r, t = self._rec(pc), now()
        if status != r["cur"]:
            r["cur"], r["since"] = status, t
        if status not in ("online", "offline") or t - r["since"] < STABLE_S or status == r["announced"]:
            return
        first = r["announced"] is None
        r["announced"] = status
        if first:
            return                            # Zustand beim Start des Hubs nicht melden
        if status == "online":
            self._fire("PC ist online", f"{name} ist hochgefahren.", f"pcc-{pc}-state")
        elif t >= r["expect_off"]:
            self._fire("PC ist offline", f"{name} ist nicht mehr erreichbar.", f"pcc-{pc}-state")

    def on_snapshot(self, pc: str, name: str, snap: dict) -> None:
        r, t = self._rec(pc), now()
        if self.jobs:
            jobs = snap.get("jobs") or ([snap["job"]] if snap.get("job") else [])
            for j in jobs:
                jid, st = j.get("job_id"), j.get("state")
                if not jid:
                    continue
                if st in ("queued", "running"):
                    r["jobs"][jid] = "active"
                elif st in ("done", "error"):
                    if r["jobs"].get(jid) == "active":
                        label = f"{j.get('tool', 'Job')}: {j.get('title') or 'ohne Titel'}"
                        if st == "done":
                            self._fire("KI-Job fertig", f"{name} – {label}", f"pcc-{pc}-job-{jid}")
                        else:
                            self._fire("KI-Job fehlgeschlagen", f"{name} – {label}. {j.get('message') or ''}".strip(), f"pcc-{pc}-job-{jid}")
                    r["jobs"][jid] = "final"
            if len(r["jobs"]) > 200:
                r["jobs"] = dict(list(r["jobs"].items())[-100:])
        temp = (snap.get("gpu") or {}).get("temp_c")
        if self.temp_limit > 0 and temp is not None:
            if temp >= self.temp_limit:
                r["hot_since"] = r["hot_since"] or t
                if t - r["hot_since"] >= HOT_AFTER_S and t - r["last_hot"] >= HOT_COOLDOWN_S:
                    r["last_hot"] = t
                    self._fire("GPU sehr heiß", f"{name}: {temp} °C seit über {int(t - r['hot_since'])} s (Grenze {self.temp_limit} °C).", f"pcc-{pc}-hot")
            elif temp < self.temp_limit - HOT_HYSTERESIS:
                r["hot_since"] = None
