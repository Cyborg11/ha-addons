"""Hub-Logik: Agent-Überwachung, Status (online/offline/waking), Snapshot-Relay."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import websockets

EXPECTED_API_VERSION = 1
WAKE_TIMEOUT_S = 120
POLL_INTERVAL_S = 2.5
# Aufwecken-Varianten (Option wake_mode, je PC einstellbar):
#   standby: PC schläft im Energiesparmodus; Sitzung, Agent und Steam laufen nach dem Aufwecken sofort weiter.
#   cold:    PC ist heruntergefahren (Autologin nötig); Windows muss booten, sich anmelden, der Agent und Steam starten.
WAKE_MODES = {
    "standby": {"timeout_s": 120, "launch_delay_s": 5},
    "cold": {"timeout_s": 300, "launch_delay_s": 25},
}
LAUNCH_GRACE_S = 120          # so lange nach Ablauf der Wartezeit darf ein „Aufwecken und starten“ noch auf den Agenten warten
LAUNCH_RETRY_S = 5            # Abstand der Startversuche, wenn der Agent (noch) nicht antwortet
RESULT_SHOW_S = 120           # so lange meldet der Hub das Ergebnis eines Spielstarts an die Oberfläche


def wake_params(opts: dict) -> tuple[str, int, int]:
    """(Modus, Wartezeit bis der Agent antworten muss, Pause nach „online“ bis zum Spielstart) aus den Optionen."""
    mode = opts.get("wake_mode") if opts.get("wake_mode") in WAKE_MODES else "standby"

    def pick(key: str, lo: int, hi: int, default: int) -> int:
        v = opts.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else default

    base = WAKE_MODES[mode]
    return mode, pick("wake_timeout_s", 30, 900, base["timeout_s"]), pick("launch_delay_s", 0, 180, base["launch_delay_s"])


def compute_status(online: bool, wake_started: float | None, now: float, timeout_s: float = WAKE_TIMEOUT_S) -> str:
    if online:
        return "online"
    if wake_started is not None and now - wake_started < timeout_s:
        return "waking"
    return "offline"


def brief_stats(snap: dict) -> dict:
    """Wenige Kennzahlen aus einem Snapshot, damit die Offline-Seite zeigen kann, wie es dem PC zuletzt ging."""
    g, c, r = snap.get("gpu") or {}, snap.get("cpu") or {}, snap.get("ram") or {}
    ram = round(100 * r["used_mb"] / r["total_mb"]) if r.get("total_mb") and r.get("used_mb") is not None else None
    return {"cpu": None if c.get("util_pct") is None else round(c["util_pct"]), "ram": ram,
            "gpu": g.get("util_pct"), "temp": g.get("temp_c"), "uptime_s": snap.get("uptime_s")}


class Hub:
    def __init__(self, opts: dict, pc_id: str = "pc1", name: str | None = None):
        self.opts = opts
        self.pc_id = pc_id
        self.name = name
        host, port = opts.get("agent_host", ""), int(opts.get("agent_port", 8765))
        self.http_base = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/ws"
        self.status = "offline"
        self.api_version: int | None = None
        self.agent_host: str | None = None
        self.features: list[str] = []         # Zusatzfunktionen des Agenten (/health), leer bei älteren Agenten
        self.snapshot: dict | None = None
        self.last_seen: float | None = None   # Zeitpunkt der letzten erfolgreichen Statusprüfung (Unix-Zeit)
        self.last_stats: dict | None = None   # letzte Kennzahlen vor dem Ausfall (für die Offline-Seite)
        self.wake_started: float | None = None
        self.wake_mode, self.wake_timeout, self.launch_delay = wake_params(opts)
        self.pending_launch: dict | None = None   # {"appid","name","since","online_since","next_try"} – Spiel, das nach dem Aufwecken startet
        self.launch_result: dict | None = None    # {"appid","name","ok","message","at"} des letzten Versuchs
        self.on_launch = None                     # Rückruf(hub, result) beim Ende eines wartenden Spielstarts (Protokoll)
        self.clients: set = set()
        self.on_snapshot = None               # Rückruf(pc_id, snapshot), z. B. für den Langzeitverlauf
        self.on_status = None                 # Rückruf(hub) nach jeder Statusprüfung
        self._upstream: asyncio.Task | None = None

    # --- Zustand -----------------------------------------------------------
    def message(self) -> dict:
        left = None
        if self.status == "waking" and self.wake_started is not None:
            left = max(0, round(self.wake_timeout - (time.time() - self.wake_started)))
        return {
            "pc": self.pc_id,
            "name": self.name,
            "status": self.status,
            "api_ok": self.api_version in (None, EXPECTED_API_VERSION),
            "api_version": self.api_version,
            "api_expected": EXPECTED_API_VERSION,
            "host": self.agent_host,
            "waking_left": left,
            "waking_total": self.wake_timeout,
            "wake_mode": self.wake_mode,
            "pending_launch": self.public_pending(),
            "launch_result": self.public_result(),
            "last_seen": self.last_seen,
            "last_stats": self.last_stats,
            "wol_configured": bool(self.opts.get("pc_mac")),
            "snapshot": self.snapshot,
            "tools": self.tools(),
            "features": self.features,
        }

    def tools(self) -> list[dict]:
        """Kacheln für den Tab „KI-Tools“ (nur http/https-Adressen)."""
        out = []
        for t in self.opts.get("tools") or []:
            url = str(t.get("url", "")).strip()
            if url.lower().startswith(("http://", "https://")) and t.get("name"):
                out.append({"name": str(t["name"])[:60], "url": url})
        return out

    async def broadcast(self) -> None:
        if not self.clients:
            return
        text = json.dumps(self.message())
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)

    def start_wake(self) -> None:
        self.wake_started = time.time()
        if self.status == "offline":
            self.status = "waking"

    # --- Aufwecken und starten ---------------------------------------------
    def _now(self) -> float:
        return time.time()

    @property
    def launch_expiry(self) -> int:
        return self.wake_timeout + LAUNCH_GRACE_S

    def queue_launch(self, appid: int, name: str) -> None:
        self.pending_launch = {"appid": appid, "name": name, "since": self._now(), "online_since": None, "next_try": 0.0}
        self.launch_result = None

    def cancel_launch(self, appid: int | None = None) -> bool:
        p = self.pending_launch
        if not p or (appid is not None and p["appid"] != appid):
            return False
        self.pending_launch = None
        return True

    def public_pending(self) -> dict | None:
        p = self.pending_launch
        if not p:
            return None
        return {"appid": p["appid"], "name": p["name"], "left_s": max(0, round(self.launch_expiry - (self._now() - p["since"])))}

    def public_result(self) -> dict | None:
        r = self.launch_result
        if not r or self._now() - r["at"] > RESULT_SHOW_S:
            return None
        return r

    def _finish_launch(self, ok: bool, message: str) -> None:
        p = self.pending_launch
        self.pending_launch = None
        if not p:
            return
        self.launch_result = {"appid": p["appid"], "name": p["name"], "ok": ok, "message": message, "at": self._now()}
        if self.on_launch:
            try:
                self.on_launch(self, self.launch_result)
            except Exception:
                pass

    async def _launch_tick(self) -> None:
        """Startet das vorgemerkte Spiel, sobald der PC online ist, Steam gemeldet wird und die Pause (launch_delay) vorbei ist."""
        p = self.pending_launch
        if not p:
            return
        now = self._now()
        if now - p["since"] > self.launch_expiry:
            self._finish_launch(False, "Der PC hat sich nicht rechtzeitig gemeldet. Läuft er, aber der Agent nicht (z. B. keine Anmeldung nach dem Start), "
                                       "am PC anmelden oder Autologin bzw. Energiesparmodus nutzen.")
            return
        if self.status != "online" or "steam" not in self.features:
            p["online_since"] = None
            return
        if p["online_since"] is None:
            p["online_since"] = now
        if now - p["online_since"] < self.launch_delay or now < p["next_try"]:
            return
        code, content, _ = await self.agent_request("POST", f"/api/steam/games/{p['appid']}/launch", None, {"force": False}, 20.0)
        if code == 200:
            self._finish_launch(True, "Spiel gestartet.")
        elif code in (400, 404, 409):
            try:
                detail = json.loads(content).get("detail")
            except Exception:
                detail = None
            self._finish_launch(False, str(detail or f"Start abgelehnt ({code})")[:200])
        else:
            p["next_try"] = now + LAUNCH_RETRY_S               # Agent/Steam noch nicht bereit: später nochmal

    # --- Agent-Anbindung ---------------------------------------------------
    async def _relay(self) -> None:
        url = f"{self.ws_url}?token={self.opts.get('agent_token', '')}"
        try:
            async with websockets.connect(url, open_timeout=3) as ws:
                async for raw in ws:
                    self.snapshot = json.loads(raw)
                    self.last_stats = brief_stats(self.snapshot)
                    if self.on_snapshot:
                        try:
                            self.on_snapshot(self.pc_id, self.snapshot)
                        except Exception:
                            pass
                    await self.broadcast()
        except Exception:
            pass

    async def poll_once(self, client: httpx.AsyncClient) -> None:
        online = False
        try:
            r = await client.get(f"{self.http_base}/health")
            data = r.json()
            online = r.status_code == 200
            self.api_version = data.get("api_version")
            self.agent_host = data.get("host")
            self.features = [f for f in (data.get("features") or []) if isinstance(f, str)]
        except Exception:
            pass
        if online:
            self.wake_started = None
            self.last_seen = time.time()
        self.status = compute_status(online, self.wake_started, time.time(), self.wake_timeout)
        try:
            await self._launch_tick()
        except Exception:
            pass
        if self.on_status:
            try:
                self.on_status(self)
            except Exception:
                pass
        if online:
            if self._upstream is None or self._upstream.done():
                self._upstream = asyncio.create_task(self._relay())
        else:
            self.snapshot = None
            if self._upstream and not self._upstream.done():
                self._upstream.cancel()
        await self.broadcast()

    async def run(self) -> None:
        if not self.opts.get("agent_host"):
            return
        async with httpx.AsyncClient(timeout=2.0) as client:
            while True:
                await self.poll_once(client)
                await asyncio.sleep(POLL_INTERVAL_S)

    async def agent_action(self, name: str, body: dict | None) -> tuple[int, dict]:
        """Leitet eine Aktion an den Agenten weiter (Agent-Token bleibt im Hub)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{self.http_base}/api/action/{name}",
                    json=body or {},
                    headers={"Authorization": f"Bearer {self.opts.get('agent_token', '')}"},
                )
            try:
                data = r.json()
            except Exception:
                data = {"detail": r.text[:200]}
            return r.status_code, data
        except Exception as e:
            return 502, {"detail": f"Agent nicht erreichbar: {e.__class__.__name__}"}

    def _agent_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.opts.get('agent_token', '')}"}

    async def agent_upload_targets(self) -> tuple[int, dict]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.http_base}/api/upload/targets", headers=self._agent_headers())
            return r.status_code, r.json()
        except Exception as e:
            return 502, {"detail": f"Agent nicht erreichbar: {e.__class__.__name__}"}

    async def agent_upload(self, stream, filename: str, target: str | None, content_length: str | None) -> tuple[int, dict]:
        """Streamt den Request-Body direkt an den Agenten weiter (nichts landet auf dem Pi)."""
        headers = {**self._agent_headers(), "Content-Type": "application/octet-stream"}
        if content_length:
            headers["Content-Length"] = content_length
        params = {"filename": filename}
        if target:
            params["target"] = target
        try:
            timeout = httpx.Timeout(connect=5.0, read=900.0, write=900.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{self.http_base}/api/upload", params=params, headers=headers, content=stream)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, {"detail": r.text[:200]}
        except Exception as e:
            return 502, {"detail": f"Upload fehlgeschlagen: {e.__class__.__name__}"}

    async def agent_job_preview(self, job_id: str) -> tuple[int, bytes, str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.http_base}/api/job/{job_id}/preview", headers=self._agent_headers())
            return r.status_code, r.content, r.headers.get("content-type", "application/octet-stream")
        except Exception:
            return 502, b"", "text/plain"

    async def agent_fetch(self, method: str, path: str, params: dict | None = None, body=None, timeout: float = 15.0,
                          extra_headers: dict | None = None) -> tuple[int, bytes, str, dict]:
        """Wie agent_request, liefert zusätzlich die Antwort-Header (ETag) und kann Header wie If-None-Match mitschicken."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, f"{self.http_base}{path}", params=params, json=body,
                                         headers={**self._agent_headers(), **(extra_headers or {})})
            return r.status_code, r.content, r.headers.get("content-type", "application/octet-stream"), dict(r.headers)
        except Exception as e:
            return 502, json.dumps({"detail": f"Agent nicht erreichbar: {e.__class__.__name__}"}).encode(), "application/json", {}

    async def agent_request(self, method: str, path: str, params: dict | None = None, body=None,
                            timeout: float = 15.0) -> tuple[int, bytes, str]:
        """Reicht einen Aufruf an den Agenten durch (der Agent-Token bleibt im Hub). Gibt (Status, Inhalt, Content-Type) zurück."""
        code, content, ctype, _ = await self.agent_fetch(method, path, params, body, timeout)
        return code, content, ctype

    def stop(self) -> None:
        if self._upstream:
            self._upstream.cancel()
