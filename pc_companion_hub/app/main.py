"""PC-Companion Hub – liefert die PWA aus, relayt Live-Daten, weckt den PC."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .hub import Hub
from .wol import send_magic_packet

log = logging.getLogger("pc-companion-hub")
STATIC = Path(__file__).parent / "static"
ALLOWED_ACTIONS = {
    "lock", "sleep", "shutdown", "restart", "cancel_shutdown", "volume", "mute",
    "media_play_pause", "media_next", "media_prev", "open_url",
}


def load_options() -> dict:
    path = Path(os.environ.get("HUB_OPTIONS", "/data/options.json"))
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def token_ok(expected: str, given: str | None) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(expected, given)


def create_app(opts: dict | None = None) -> FastAPI:
    opts = load_options() if opts is None else opts
    hub = Hub(opts)
    if not opts.get("ui_token"):
        log.warning("ui_token ist nicht gesetzt – alle API-Aufrufe werden abgelehnt.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(hub.run())
        yield
        task.cancel()
        hub.stop()

    app = FastAPI(title="PC-Companion Hub", lifespan=lifespan)
    app.state.hub = hub

    async def require_ui_token(authorization: str | None = Header(default=None)):
        given = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
        if not token_ok(opts.get("ui_token", ""), given):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/status", dependencies=[Depends(require_ui_token)])
    def status():
        return hub.message()

    @app.post("/api/wake", dependencies=[Depends(require_ui_token)])
    def wake():
        if not opts.get("pc_mac"):
            raise HTTPException(status_code=400, detail="pc_mac ist nicht konfiguriert")
        try:
            send_magic_packet(opts["pc_mac"], opts.get("broadcast_ip") or "255.255.255.255")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=502, detail=f"Senden fehlgeschlagen: {e}")
        hub.start_wake()
        return {"ok": True, "status": hub.status}

    @app.post("/api/action/{name}", dependencies=[Depends(require_ui_token)])
    async def action(name: str, body: dict | None = Body(default=None)):
        if name not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=404, detail="unbekannte Aktion")
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        code, data = await hub.agent_action(name, body)
        return JSONResponse(data, status_code=code)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if not token_ok(opts.get("ui_token", ""), websocket.query_params.get("token")):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        hub.clients.add(websocket)
        try:
            await websocket.send_text(json.dumps(hub.message()))
            while True:
                await websocket.receive_text()  # hält die Verbindung; Eingaben ignoriert
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.clients.discard(websocket)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app() if os.environ.get("HUB_NO_AUTOCREATE") != "1" else None
