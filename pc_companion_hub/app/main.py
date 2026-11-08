"""PC-Companion Hub – liefert die PWA aus, relayt Live-Daten, weckt den PC."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import audit as audit_mod, auth
from .hub import Hub
from .wol import send_magic_packet

try:                                     # QR-Code der Kopplung; ohne segno bleibt der Link zum Abtippen
    import segno
except ImportError:                      # pragma: no cover
    segno = None

log = logging.getLogger("pc-companion-hub")
# Home-Assistant-Ingress (Supervisor) hat diese Quelladresse; HA hat den Nutzer dann schon angemeldet.
TRUSTED_PROXY_IPS = {"172.30.32.2"}
STATIC = Path(__file__).parent / "static"
ALLOWED_ACTIONS = {
    "lock", "sleep", "shutdown", "restart", "restart_agent", "cancel_shutdown", "volume", "mute",
    "media_play_pause", "media_next", "media_prev", "open_url",
}


def load_options() -> dict:
    path = Path(os.environ.get("HUB_OPTIONS", "/data/options.json"))
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def token_ok(expected: str, given: str | None) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(expected, given)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "pc"


def build_pcs(opts: dict) -> list[tuple[str, str | None, dict]]:
    """(id, Name, Optionen) je PC. Neue Form: Liste ``pcs``; alte Form (agent_host, ...) wird zum einzigen PC."""
    out, used = [], set()
    for i, entry in enumerate(opts.get("pcs") or []):
        host = str(entry.get("host") or "").strip()
        if not host:
            continue
        name = str(entry.get("name") or "").strip() or f"PC {i + 1}"
        base = slugify(name)
        pid, n = base, 2
        while pid in used:
            pid, n = f"{base}-{n}", n + 1
        used.add(pid)
        merged = dict(opts)
        merged.update(
            agent_host=host, agent_port=int(entry.get("port") or 8765), agent_token=entry.get("token") or "",
            pc_mac=entry.get("mac") or "",
            broadcast_ip=entry.get("broadcast_ip") or opts.get("broadcast_ip") or "255.255.255.255",
        )
        if entry.get("tools"):
            merged["tools"] = entry["tools"]
        out.append((pid, name, merged))
    if not out:
        out.append(("pc1", None, dict(opts)))
    return out


def qr_data_uri(text: str) -> str | None:
    if segno is None:
        return None
    return segno.make(text, error="m").svg_data_uri(scale=6, border=2)


def clean_base(base) -> str | None:
    """Basisadresse für den Kopplungslink (http/https, ohne Zeilenumbrüche, ohne Fragment)."""
    if not isinstance(base, str):
        return None
    base = base.strip().split("#")[0]
    return base if re.fullmatch(r"https?://[^\s<>\"']{1,200}", base) else None


def create_app(opts: dict | None = None, data_dir: str | Path | None = None) -> FastAPI:
    opts = load_options() if opts is None else opts
    clients: set = set()
    hubs: dict[str, Hub] = {}
    for pid, pname, popts in build_pcs(opts):
        hubs[pid] = Hub(popts, pid, pname)
        hubs[pid].clients = clients           # alle PCs senden an dieselben Browser
    hub = next(iter(hubs.values()))           # Standard-PC (erster Eintrag)
    data_dir = Path(data_dir or os.environ.get("HUB_DATA", "/data"))
    devices = auth.DeviceStore(data_dir / "devices.json")
    pairing = auth.Pairing()
    limiter = auth.Limiter()
    ws_devices: dict[WebSocket, str] = {}
    audit = audit_mod.AuditLog(data_dir / "audit.log")
    if not opts.get("ui_token") and not opts.get("pin"):
        log.warning("Weder pin noch ui_token sind gesetzt – alle API-Aufrufe werden abgelehnt.")
    elif opts.get("pin") and len(str(opts["pin"])) < 6:
        log.warning("Die PIN hat weniger als 6 Zeichen – besser länger wählen (Sperre nach 5 Fehlversuchen besteht trotzdem).")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(h.run()) for h in hubs.values()]
        yield
        for t in tasks:
            t.cancel()
        for h in hubs.values():
            h.stop()

    app = FastAPI(title="PC-Companion Hub", lifespan=lifespan)
    app.state.hub = hub
    app.state.hubs = hubs

    def get_hub(pc: str | None = Query(default=None)) -> Hub:
        if pc is None:
            return hub
        if pc not in hubs:
            raise HTTPException(status_code=404, detail="unbekannter PC")
        return hubs[pc]

    def pc_list() -> list[dict]:
        return [{"id": pid, "name": h.name} for pid, h in hubs.items()]

    def principal(given: str | None, ip: str) -> dict | None:
        """Wer ruft auf? Hauptschlüssel (ui_token), gekoppeltes Gerät oder HA-Ingress."""
        if token_ok(opts.get("ui_token", ""), given):
            return {"kind": "master", "role": "full"}
        dev = devices.verify(given)
        if dev:
            return {"kind": "device", "id": dev["id"], "role": dev.get("role", "full")}
        if ip in TRUSTED_PROXY_IPS:
            return {"kind": "ingress", "role": "full"}
        return None

    def who_label(who: dict | None) -> str:
        if not who:
            return "unbekannt"
        if who["kind"] == "device":
            dev = devices.get(who["id"])
            return dev["name"] if dev else "Gerät " + who["id"]
        return {"master": "Hauptschlüssel", "ingress": "Home Assistant"}.get(who["kind"], who["kind"])

    def record(request: Request, what: str, pc: str | None = None, detail: str | None = None, ok: bool = True) -> None:
        audit.add(who_label(getattr(request.state, "principal", None)), what, pc, detail, ok)

    def client_ip(conn) -> str:
        return conn.client.host if conn.client else ""

    async def require_ui_token(request: Request, authorization: str | None = Header(default=None)):
        given = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None
        who = principal(given, client_ip(request))
        if not who:
            raise HTTPException(status_code=401, detail="unauthorized")
        request.state.principal = who

    async def require_write(request: Request, authorization: str | None = Header(default=None)):
        """Wie require_ui_token, aber Nur-Ansicht-Geräte werden abgewiesen."""
        await require_ui_token(request, authorization)
        if request.state.principal.get("role") != "full":
            raise HTTPException(status_code=403, detail="Dieses Gerät darf nur ansehen")

    def login_response(name: str, role: str = "full") -> dict:
        dev, token = devices.create(name, role)
        return {"token": token, "device": dev}

    def guard(request: Request) -> str:
        """Prüft die Sperre; gibt die Client-IP zurück."""
        ip = client_ip(request)
        wait = limiter.wait_s(ip)
        if wait:
            raise HTTPException(status_code=429, detail=f"Zu viele Versuche. Bitte in {max(1, wait // 60)} Min. erneut.",
                                headers={"Retry-After": str(wait)})
        return ip

    def device_label(body: dict, request: Request) -> str:
        name = body.get("name") if isinstance(body, dict) else None
        return auth.clean_name(name, auth.device_name_from_ua(request.headers.get("user-agent")))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/auth/info")
    def auth_info(request: Request):
        """Ohne Anmeldung abrufbar: sagt dem Browser, wie er sich anmelden kann."""
        pin = str(opts.get("pin") or "")
        if request.headers.get("x-ingress-path") and client_ip(request) not in TRUSTED_PROXY_IPS:
            log.warning("Ingress-Anfrage von %s wird nicht als vertrauenswürdig behandelt (erwartet: %s) – bitte melden.",
                        client_ip(request), ", ".join(sorted(TRUSTED_PROXY_IPS)))
        return {"trusted": client_ip(request) in TRUSTED_PROXY_IPS, "pin": bool(pin), "pin_numeric": pin.isdigit(),
                "qr": segno is not None}

    @app.post("/api/login")
    def login(request: Request, body: dict | None = Body(default=None)):
        ip = guard(request)
        given = body.get("secret") if isinstance(body, dict) else None
        if not isinstance(given, str) or not (auth.secret_matches(str(opts.get("pin") or ""), given)
                                              or auth.secret_matches(opts.get("ui_token", ""), given)):
            limiter.fail(ip)
            audit.add("unbekannt", "Anmeldung fehlgeschlagen", detail=ip, ok=False)
            raise HTTPException(status_code=401, detail="PIN oder Token falsch")
        limiter.ok(ip)
        resp = login_response(device_label(body, request))
        audit.add(resp["device"]["name"], "Angemeldet (PIN)", detail=ip)
        return resp

    @app.post("/api/pair", dependencies=[Depends(require_write)])
    def pair(request: Request, body: dict | None = Body(default=None)):
        role = body.get("role") if isinstance(body, dict) and body.get("role") in auth.ROLES else "full"
        base = clean_base(body.get("base") if isinstance(body, dict) else None) or clean_base(opts.get("public_url"))
        if not base:
            raise HTTPException(status_code=400, detail="Basisadresse fehlt (http://… oder https://…)")
        code = pairing.create(role)
        record(request, "Kopplung erzeugt", detail="Rolle: " + role)
        url = base.rstrip("/") + "/#pair=" + code
        return {"code": code, "url": url, "qr": qr_data_uri(url), "expires_s": auth.PAIR_TTL_S}

    @app.post("/api/pair/redeem")
    def pair_redeem(request: Request, body: dict | None = Body(default=None)):
        ip = guard(request)
        role = pairing.redeem(body.get("code") if isinstance(body, dict) else None)
        if role is None:
            limiter.fail(ip)
            audit.add("unbekannt", "Kopplung fehlgeschlagen", detail=ip, ok=False)
            raise HTTPException(status_code=401, detail="Kopplungscode ungültig oder abgelaufen")
        limiter.ok(ip)
        resp = login_response(device_label(body, request), role)
        audit.add(resp["device"]["name"], "Gerät gekoppelt (QR)", detail="Rolle: " + role)
        return resp

    @app.get("/api/devices", dependencies=[Depends(require_ui_token)])
    def list_devices(request: Request):
        who = request.state.principal
        listed = devices.public() if who["role"] == "full" else [d for d in devices.public() if d["id"] == who.get("id")]
        return {"devices": listed, "current": who.get("id"), "kind": who["kind"], "role": who["role"],
                "public_url": opts.get("public_url") or ""}

    @app.patch("/api/devices/{device_id}", dependencies=[Depends(require_write)])
    def set_device_role(device_id: str, request: Request, body: dict | None = Body(default=None)):
        role = body.get("role") if isinstance(body, dict) else None
        if role not in auth.ROLES:
            raise HTTPException(status_code=400, detail="Rolle muss full oder view sein")
        dev = devices.get(device_id)
        if not dev or not devices.set_role(device_id, role):
            raise HTTPException(status_code=404, detail="unbekanntes Gerät")
        record(request, "Rolle geändert", detail=f"{dev['name']}: {role}")
        return {"ok": True}

    @app.get("/api/audit", dependencies=[Depends(require_write)])
    def audit_log(limit: int = 50):
        return {"entries": audit.tail(limit)}

    @app.delete("/api/devices/{device_id}", dependencies=[Depends(require_ui_token)])
    async def revoke_device(device_id: str, request: Request):
        who = request.state.principal
        if who["role"] != "full" and who.get("id") != device_id:      # Nur-Ansicht-Geräte dürfen nur sich selbst abmelden
            raise HTTPException(status_code=403, detail="Dieses Gerät darf nur ansehen")
        dev = devices.get(device_id)
        if not devices.revoke(device_id):
            raise HTTPException(status_code=404, detail="unbekanntes Gerät")
        record(request, "Gerät entfernt", detail=dev["name"] if dev else device_id)
        for sock, dev_id in list(ws_devices.items()):      # offene Verbindungen des Geräts schließen
            if dev_id == device_id:
                try:
                    await sock.close(code=4401)
                except RuntimeError:
                    pass
        return {"ok": True}

    @app.get("/api/status", dependencies=[Depends(require_ui_token)])
    def status(hub: Hub = Depends(get_hub)):
        return hub.message()

    @app.get("/api/pcs", dependencies=[Depends(require_ui_token)])
    def pcs(request: Request):
        return {"pcs": pc_list(), "default": next(iter(hubs)), "role": request.state.principal["role"]}

    @app.post("/api/wake", dependencies=[Depends(require_write)])
    def wake(request: Request, hub: Hub = Depends(get_hub)):
        if not hub.opts.get("pc_mac"):
            raise HTTPException(status_code=400, detail="MAC-Adresse ist nicht konfiguriert")
        try:
            send_magic_packet(hub.opts["pc_mac"], hub.opts.get("broadcast_ip") or "255.255.255.255")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=502, detail=f"Senden fehlgeschlagen: {e}")
        hub.start_wake()
        record(request, "PC aufgeweckt", pc=hub.name or hub.pc_id)
        return {"ok": True, "status": hub.status}

    @app.post("/api/action/{name}", dependencies=[Depends(require_write)])
    async def action(name: str, request: Request, body: dict | None = Body(default=None), hub: Hub = Depends(get_hub)):
        if name not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=404, detail="unbekannte Aktion")
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        code, data = await hub.agent_action(name, body)
        detail = ", ".join(f"{k}={str(v)[:60]}" for k, v in (body or {}).items()) if isinstance(body, dict) else None
        record(request, "Aktion: " + name, pc=hub.name or hub.pc_id, detail=detail, ok=code == 200)
        return JSONResponse(data, status_code=code)

    @app.get("/api/upload/targets", dependencies=[Depends(require_write)])
    async def upload_targets(hub: Hub = Depends(get_hub)):
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        code, data = await hub.agent_upload_targets()
        return JSONResponse(data, status_code=code)

    @app.post("/api/upload", dependencies=[Depends(require_write)])
    async def upload(request: Request, filename: str, target: str | None = None, hub: Hub = Depends(get_hub)):
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        code, data = await hub.agent_upload(request.stream(), filename, target, request.headers.get("content-length"))
        record(request, "Datei gesendet", pc=hub.name or hub.pc_id, detail=f"{filename[:80]} → {target or 'Standard'}", ok=code == 200)
        return JSONResponse(data, status_code=code)

    @app.get("/api/job/{job_id}/preview", dependencies=[Depends(require_ui_token)])
    async def job_preview(job_id: str, hub: Hub = Depends(get_hub)):
        if hub.status != "online" or not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", job_id):
            raise HTTPException(status_code=404, detail="kein Vorschaubild")
        code, data, ctype = await hub.agent_job_preview(job_id)
        if code != 200:
            raise HTTPException(status_code=404, detail="kein Vorschaubild")
        return Response(content=data, media_type=ctype, headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        who = principal(websocket.query_params.get("token"), client_ip(websocket))
        if not who:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        clients.add(websocket)
        if who["kind"] == "device":
            ws_devices[websocket] = who["id"]
        try:
            await websocket.send_text(json.dumps({"pcs": pc_list(), "default": next(iter(hubs)), "role": who["role"]}))
            for h in hubs.values():
                await websocket.send_text(json.dumps(h.message()))
            while True:
                await websocket.receive_text()  # hält die Verbindung; Eingaben ignoriert
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.discard(websocket)
            ws_devices.pop(websocket, None)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app() if os.environ.get("HUB_NO_AUTOCREATE") != "1" else None
