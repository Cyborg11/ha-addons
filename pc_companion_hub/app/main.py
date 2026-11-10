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

from . import audit as audit_mod, auth, history as history_mod, logredact, notify as notify_mod
from .hub import Hub
from .wol import send_magic_packet

try:                                     # QR-Code der Kopplung; ohne segno bleibt der Link zum Abtippen
    import segno
except ImportError:                      # pragma: no cover
    segno = None

log = logging.getLogger("pc-companion-hub")
logredact.install()          # Token aus Adressen im Zugriffsprotokoll entfernen
# Home-Assistant-Ingress (Supervisor) hat diese Quelladresse; HA hat den Nutzer dann schon angemeldet.
TRUSTED_PROXY_IPS = {"172.30.32.2"}
STATIC = Path(__file__).parent / "static"
ALLOWED_ACTIONS = {
    "lock", "sleep", "shutdown", "restart", "restart_agent", "cancel_shutdown", "volume", "mute",
    "media_play_pause", "media_next", "media_prev", "open_url", "clipboard_set", "monitor_off",
}
SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
# Abfrageparameter, die je Funktion an den Agenten weitergereicht werden dürfen
API_LOCK_AFTER = 20        # falsche Bearer-Token je Adresse, dann 15 Minuten Sperre
API_GLOBAL_LIMIT = 300     # insgesamt pro Stunde
GALLERY_PARAMS = ("folder", "name", "w", "limit", "offset", "download")
STEAM_KINDS = ("cover", "header", "hero", "logo", "icon")
STEAM_OPEN = {"bigpicture": "Big Picture", "downloads": "Downloads öffnen", "library": "Bibliothek öffnen", "exit": "Steam beendet"}


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


async def _no_send(title, message, tag=None):
    return False, "nicht eingerichtet"


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
    # Falsche Bearer-Token an der API (Ausprobieren des ui_token): großzügiger als bei der PIN, weil ein abgemeldetes Gerät
    # ein paar Mal anklopft, bevor es zur Anmeldung wechselt.
    api_limiter = auth.Limiter(lock_after=API_LOCK_AFTER, lock_s=auth.LOCK_S, global_limit=API_GLOBAL_LIMIT)
    ws_devices: dict[WebSocket, str] = {}
    audit = audit_mod.AuditLog(data_dir / "audit.log")
    history = history_mod.History(data_dir / "history.db")
    for pid_, h_ in hubs.items():                 # „zuletzt online“ auch nach einem Neustart des Hubs kennen
        h_.last_seen = history.last_t(pid_)
    ha = notify_mod.HaNotifier(opts.get("notify_service", ""), os.environ.get("SUPERVISOR_TOKEN"),
                               os.environ.get("HA_API_URL", "http://supervisor/core/api"))
    notifier = notify_mod.Notifier(opts, ha.send if ha.configured else _no_send)

    def pc_label(h: Hub) -> str:
        return h.name or h.agent_host or h.pc_id

    def on_snapshot(pc_id: str, snap: dict) -> None:
        history.feed(pc_id, snap)
        notifier.on_snapshot(pc_id, pc_label(hubs[pc_id]), snap)

    for h in hubs.values():
        h.on_snapshot = on_snapshot
        h.on_status = lambda hub_, n=notifier: n.on_status(hub_.pc_id, pc_label(hub_), hub_.status)
    if not opts.get("ui_token") and not opts.get("pin"):
        log.warning("Weder pin noch ui_token sind gesetzt – alle API-Aufrufe werden abgelehnt.")
    elif opts.get("ui_token") and len(str(opts["ui_token"])) < 16:
        log.warning("Der ui_token hat weniger als 16 Zeichen – besser ein langes Zufallstoken wählen.")
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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")      # kein MIME-Raten (hochgeladene/relayte Dateien)
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp
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
        """Wer ruft auf? Hauptschlüssel (ui_token), gekoppeltes Gerät oder HA-Ingress.
        Wer zu oft ein falsches Token vorzeigt, wird gesperrt (dann zählt auch ein richtiges nicht mehr)."""
        locked = bool(given) and api_limiter.wait_s(ip) > 0
        if not locked:
            if token_ok(opts.get("ui_token", ""), given):
                return {"kind": "master", "role": "full"}
            dev = devices.verify(given)
            if dev:
                return {"kind": "device", "id": dev["id"], "role": dev.get("role", "full")}
        if ip in TRUSTED_PROXY_IPS:
            return {"kind": "ingress", "role": "full"}
        if given and not locked:
            api_limiter.fail(ip)
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
            wait = api_limiter.wait_s(client_ip(request)) if given else 0
            if wait:
                raise HTTPException(status_code=429, detail="Zu viele falsche Anmeldungen.", headers={"Retry-After": str(wait)})
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

    # ---- Zusatzfunktionen des Agenten (Phase 8): Aufrufe werden durchgereicht ----
    async def relay(request: Request, hub: Hub, method: str, path: str, *, params: dict | None = None, body=None,
                    what: str | None = None, detail: str | None = None, timeout: float = 15.0, cache: str | None = None) -> Response:
        """cache: Cache-Control für Antworten, die der Browser behalten darf (Steam-Bilder); dann gehen ETag und If-None-Match durch."""
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        inm = request.headers.get("if-none-match") if cache else None
        code, content, ctype, rh = await hub.agent_fetch(method, path, params, body, timeout, {"If-None-Match": inm} if inm else None)
        if what:
            record(request, what, pc=hub.name or hub.pc_id, detail=detail, ok=code < 300)
        headers = {"Cache-Control": cache if cache and code in (200, 304) else "no-store"}
        if cache and code in (200, 304) and rh.get("etag"):
            headers["ETag"] = rh["etag"]
        return Response(content=content if code != 304 else b"", status_code=code, media_type=ctype, headers=headers)

    def take(request: Request, allowed: tuple[str, ...]) -> dict:
        return {k: v for k, v in request.query_params.items() if k in allowed}

    def safe_id(value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise HTTPException(status_code=404, detail="ungültige ID")
        return value

    @app.get("/api/power-plan", dependencies=[Depends(require_ui_token)])
    async def power_plan_get(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/power-plan")

    @app.post("/api/power-plan", dependencies=[Depends(require_write)])
    async def power_plan_set(request: Request, body: dict | None = Body(default=None), hub: Hub = Depends(get_hub)):
        body = body if isinstance(body, dict) else {}
        allowed = {k: body[k] for k in ("timer_minutes", "mode", "after_job") if k in body}
        detail = ", ".join(f"{k}={v}" for k, v in allowed.items())
        return await relay(request, hub, "POST", "/api/power-plan", body=allowed, what="Energie-Plan gesetzt", detail=detail)

    @app.delete("/api/power-plan", dependencies=[Depends(require_write)])
    async def power_plan_cancel(request: Request, which: str = "all", hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "DELETE", "/api/power-plan", params={"which": which}, what="Energie-Plan abgebrochen", detail=which)

    @app.get("/api/programs", dependencies=[Depends(require_write)])
    async def programs_list(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/programs")

    @app.post("/api/programs/{pid}/{op}", dependencies=[Depends(require_write)])
    async def program_op(pid: str, op: str, request: Request, hub: Hub = Depends(get_hub)):
        if op not in ("start", "stop"):
            raise HTTPException(status_code=404, detail="unbekannte Operation")
        return await relay(request, hub, "POST", f"/api/programs/{safe_id(pid)}/{op}", what=f"Programm {'gestartet' if op == 'start' else 'beendet'}",
                           detail=pid, timeout=20.0)

    @app.get("/api/processes", dependencies=[Depends(require_write)])
    async def processes_list(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/processes", params=take(request, ("sort", "limit")), timeout=20.0)

    @app.get("/api/top", dependencies=[Depends(require_ui_token)])
    async def top_usage(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/top", params=take(request, ("n",)), timeout=20.0)

    @app.post("/api/processes/{pid}/kill", dependencies=[Depends(require_write)])
    async def process_kill(pid: int, request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "POST", f"/api/processes/{pid}/kill", what="Prozess beendet", detail=f"PID {pid}", timeout=20.0)

    @app.get("/api/gallery", dependencies=[Depends(require_ui_token)])
    async def gallery_list(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/gallery", params=take(request, GALLERY_PARAMS))

    @app.get("/api/gallery/thumb", dependencies=[Depends(require_ui_token)])
    async def gallery_thumb(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/gallery/thumb", params=take(request, GALLERY_PARAMS))

    @app.get("/api/gallery/file", dependencies=[Depends(require_ui_token)])
    async def gallery_file(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/gallery/file", params=take(request, GALLERY_PARAMS), timeout=60.0)

    # ---- Steam (Phase 9): Lesen mit Ansichtsrecht, alles Verändernde nur mit Schreibrecht und im Protokoll ----
    async def steam_label(hub: Hub, appid: int) -> str:
        if hub.status != "online":
            return f"AppID {appid}"
        code, content, _ = await hub.agent_request("GET", f"/api/steam/games/{appid}")
        try:
            return f"{json.loads(content)['name']} ({appid})" if code == 200 else f"AppID {appid}"
        except (ValueError, KeyError, TypeError):
            return f"AppID {appid}"

    def steam_appid(appid: int) -> int:
        if not 0 < appid < 2 ** 32:
            raise HTTPException(status_code=400, detail="ungültige AppID")
        return appid

    @app.get("/api/steam/status", dependencies=[Depends(require_ui_token)])
    async def steam_status(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/steam/status")

    @app.get("/api/steam/downloads", dependencies=[Depends(require_ui_token)])
    async def steam_downloads(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/steam/downloads")

    @app.get("/api/steam/games", dependencies=[Depends(require_ui_token)])
    async def steam_games(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/steam/games", params=take(request, ("sort", "q")))

    @app.get("/api/steam/games/{appid}", dependencies=[Depends(require_ui_token)])
    async def steam_game(appid: int, request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", f"/api/steam/games/{steam_appid(appid)}")

    @app.get("/api/steam/art/{appid}/{kind}", dependencies=[Depends(require_ui_token)])
    async def steam_art(appid: int, kind: str, request: Request, hub: Hub = Depends(get_hub)):
        if kind not in STEAM_KINDS:
            raise HTTPException(status_code=400, detail="ungültige Bildart")
        return await relay(request, hub, "GET", f"/api/steam/art/{steam_appid(appid)}/{kind}", params=take(request, ("w",)),
                           timeout=20.0, cache="private, max-age=86400")

    @app.post("/api/steam/games/{appid}/launch", dependencies=[Depends(require_write)])
    async def steam_launch(appid: int, request: Request, body: dict | None = Body(default=None), hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        force = bool((body or {}).get("force"))
        return await relay(request, hub, "POST", f"/api/steam/games/{appid}/launch", body={"force": force},
                           what="Spiel gestartet", detail=await steam_label(hub, appid), timeout=20.0)

    @app.post("/api/steam/games/{appid}/stop", dependencies=[Depends(require_write)])
    async def steam_stop(appid: int, request: Request, hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        return await relay(request, hub, "POST", f"/api/steam/games/{appid}/stop", what="Spiel beendet",
                           detail=await steam_label(hub, appid), timeout=25.0)

    @app.post("/api/steam/open/{what}", dependencies=[Depends(require_write)])
    async def steam_open(what: str, request: Request, hub: Hub = Depends(get_hub)):
        if what not in STEAM_OPEN:
            raise HTTPException(status_code=400, detail="unbekannte Steam-Aktion")
        return await relay(request, hub, "POST", f"/api/steam/open/{what}", what="Steam: " + STEAM_OPEN[what])

    @app.get("/api/screenshot", dependencies=[Depends(require_write)])
    async def screenshot(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/screenshot", params=take(request, ("width",)), what="Screenshot", timeout=25.0)

    @app.get("/api/clipboard", dependencies=[Depends(require_write)])
    async def clipboard_get(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/clipboard", what="Zwischenablage gelesen")

    @app.post("/api/job/{job_id}/cancel", dependencies=[Depends(require_write)])
    async def job_cancel(job_id: str, request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "POST", f"/api/job/{safe_id(job_id)}/cancel", what="Job-Abbruch angefordert", detail=job_id)

    @app.get("/api/jobs/history", dependencies=[Depends(require_ui_token)])
    async def jobs_history(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/jobs/history", params=take(request, ("limit",)))

    @app.get("/api/notify", dependencies=[Depends(require_ui_token)])
    def notify_info():
        return {"configured": ha.configured, "service": ha.service if ha.configured else "", "jobs": notifier.jobs,
                "pc_state": notifier.pc_state, "temp_c": notifier.temp_limit, "last_error": ha.last_error}

    @app.post("/api/notify/test", dependencies=[Depends(require_write)])
    async def notify_test(request: Request):
        ok, text = await ha.send("PC-Companion", "Testbenachrichtigung – so melden sich deine PCs.", "pcc-test")
        record(request, "Testbenachrichtigung", detail=text, ok=ok)
        if not ok:
            raise HTTPException(status_code=502, detail=text)
        return {"ok": True}

    @app.get("/api/history", dependencies=[Depends(require_ui_token)])
    def history_query(hours: float = 1, hub: Hub = Depends(get_hub)):
        return history.query(hub.pc_id, hours)

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
        if code == 200 and name in ("shutdown", "sleep", "restart"):
            notifier.expect_power_action(hub.pc_id)         # dann keine „PC ist offline“-Meldung
        # Text der Zwischenablage nie ins Protokoll schreiben, nur die Länge
        detail = ", ".join((f"text={len(str(v))} Zeichen" if k == "text" else f"{k}={str(v)[:60]}") for k, v in (body or {}).items()) if isinstance(body, dict) else None
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
