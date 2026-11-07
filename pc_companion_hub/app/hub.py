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


def compute_status(online: bool, wake_started: float | None, now: float) -> str:
    if online:
        return "online"
    if wake_started is not None and now - wake_started < WAKE_TIMEOUT_S:
        return "waking"
    return "offline"


class Hub:
    def __init__(self, opts: dict):
        self.opts = opts
        host, port = opts.get("agent_host", ""), int(opts.get("agent_port", 8765))
        self.http_base = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/ws"
        self.status = "offline"
        self.api_version: int | None = None
        self.agent_host: str | None = None
        self.snapshot: dict | None = None
        self.wake_started: float | None = None
        self.clients: set = set()
        self._upstream: asyncio.Task | None = None

    # --- Zustand -----------------------------------------------------------
    def message(self) -> dict:
        left = None
        if self.status == "waking" and self.wake_started is not None:
            left = max(0, round(WAKE_TIMEOUT_S - (time.time() - self.wake_started)))
        return {
            "status": self.status,
            "api_ok": self.api_version in (None, EXPECTED_API_VERSION),
            "api_version": self.api_version,
            "api_expected": EXPECTED_API_VERSION,
            "host": self.agent_host,
            "waking_left": left,
            "wol_configured": bool(self.opts.get("pc_mac")),
            "snapshot": self.snapshot,
        }

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

    # --- Agent-Anbindung ---------------------------------------------------
    async def _relay(self) -> None:
        url = f"{self.ws_url}?token={self.opts.get('agent_token', '')}"
        try:
            async with websockets.connect(url, open_timeout=3) as ws:
                async for raw in ws:
                    self.snapshot = json.loads(raw)
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
        except Exception:
            pass
        if online:
            self.wake_started = None
        self.status = compute_status(online, self.wake_started, time.time())
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

    def stop(self) -> None:
        if self._upstream:
            self._upstream.cancel()
