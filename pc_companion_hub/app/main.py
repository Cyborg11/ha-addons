"""PC-Companion Hub – liefert die PWA aus, relayt Live-Daten, weckt den PC."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import audit as audit_mod, auth, history as history_mod, logredact, notify as notify_mod, stats as stats_mod
from .hub import Hub
from . import energy as energy_mod, scenes as scenes_mod, schedules as schedules_mod
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
    "lock", "sleep", "standby", "shutdown", "restart", "restart_agent", "cancel_shutdown", "volume", "mute",
    "media_play_pause", "media_next", "media_prev", "open_url", "clipboard_set", "monitor_off", "display",
}
SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}")
CRITICAL_ACTIONS = {"shutdown", "restart", "sleep", "standby"}        # mit confirm_pin nur mit PIN
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
        for key in ("wake_mode", "wake_timeout_s", "launch_delay_s"):       # je PC überschreibbar
            if entry.get(key) is not None:
                merged[key] = entry[key]
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
    pin_limiter = auth.Limiter(lock_after=5, lock_s=300, global_limit=60)            # falsche Sicherheits-PINs: nach 5 Fehlern 5 Minuten Sperre
    api_limiter = auth.Limiter(lock_after=API_LOCK_AFTER, lock_s=auth.LOCK_S, global_limit=API_GLOBAL_LIMIT)
    ws_devices: dict[WebSocket, str] = {}
    audit = audit_mod.AuditLog(data_dir / "audit.log")
    history = history_mod.History(data_dir / "history.db")
    tz = schedules_mod.resolve_tz(opts.get("timezone"))
    energy = energy_mod.EnergyMeter(data_dir / "energy.db", tz)
    try:
        price_ct = max(0.0, min(float(opts.get("strompreis_ct_kwh") or 0), 200.0))
    except (TypeError, ValueError):
        price_ct = 0.0
    for pid_, h_ in hubs.items():                 # „zuletzt online“ auch nach einem Neustart des Hubs kennen
        h_.last_seen = history.last_t(pid_)
    ha = notify_mod.HaNotifier(opts.get("notify_service", ""), os.environ.get("SUPERVISOR_TOKEN"),
                               os.environ.get("HA_API_URL", "http://supervisor/core/api"))
    notifier = notify_mod.Notifier(opts, ha.send if ha.configured else _no_send)

    def pc_label(h: Hub) -> str:
        return h.name or h.agent_host or h.pc_id

    def on_snapshot(pc_id: str, snap: dict) -> None:
        history.feed(pc_id, snap)
        energy.feed(pc_id, snap)
        notifier.on_snapshot(pc_id, pc_label(hubs[pc_id]), snap)

    def on_launch(hub_: Hub, result: dict) -> None:
        audit.add("Hub", "Spiel gestartet (nach Aufwecken)" if result["ok"] else "Spielstart nach Aufwecken fehlgeschlagen",
                  pc_label(hub_), f"{result['name']} ({result['appid']}): {result['message']}"[:300], result["ok"])

    for h in hubs.values():
        h.on_launch = on_launch
        h.on_snapshot = on_snapshot
        h.on_status = lambda hub_, n=notifier: n.on_status(hub_.pc_id, pc_label(hub_), hub_.status)
    if not opts.get("ui_token") and not opts.get("pin"):
        log.warning("Weder pin noch ui_token sind gesetzt – alle API-Aufrufe werden abgelehnt.")
    elif opts.get("ui_token") and len(str(opts["ui_token"])) < 16:
        log.warning("Der ui_token hat weniger als 16 Zeichen – besser ein langes Zufallstoken wählen.")
    elif opts.get("pin") and len(str(opts["pin"])) < 6:
        log.warning("Die PIN hat weniger als 6 Zeichen – besser länger wählen (Sperre nach 5 Fehlversuchen besteht trotzdem).")

    async def energy_ha_loop() -> None:
        """Schreibt jede Minute kWh und Kosten von heute als Sensoren nach Home Assistant (nur im Add-on, mit Supervisor-Token; abschaltbar mit energy_sensors: false)."""
        if opts.get("energy_sensors", True) is False:
            return
        while True:
            await asyncio.sleep(60)
            if not ha.token:
                continue
            try:
                for pid, h in hubs.items():
                    slug = re.sub(r"[^a-z0-9]+", "_", pid.lower()).strip("_") or "pc"
                    kwh = energy.today(pid)
                    label = h.name or pid
                    await ha.set_state(f"sensor.pc_companion_{slug}_kwh_heute", round(kwh, 3),
                                       {"unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing", "friendly_name": f"{label} Strom heute"})
                    if price_ct > 0:
                        await ha.set_state(f"sensor.pc_companion_{slug}_kosten_heute", round(kwh * price_ct / 100.0, 2),
                                           {"unit_of_measurement": "€", "device_class": "monetary", "state_class": "total", "friendly_name": f"{label} Stromkosten heute"})
            except Exception:                                              # noqa: BLE001 - nie den Hub stören
                log.exception("Strom-Sensoren nicht aktualisiert")

    health_cache: dict[str, dict] = {}

    async def health_loop() -> None:
        """Fragt alle 5 Minuten die Gesundheitsprüfung der online erreichbaren PCs ab (Feature health) und meldet neue Auffälligkeiten."""
        while True:
            await asyncio.sleep(20)
            for pid, h in hubs.items():
                try:
                    t = time.time()
                    if h.status != "online" or "health" not in h.features or t - health_cache.get(pid, {}).get("at", 0) < 300:
                        continue
                    code, content, _ = await h.agent_request("GET", "/api/system/health", None, None, 40.0)
                    if code != 200:
                        continue
                    data = json.loads(content)
                    health_cache[pid] = {"at": t, "data": data}
                    notifier.on_health(pid, pc_label(h), data.get("issues") or [])
                except Exception:                                          # noqa: BLE001 - nie den Hub stören
                    log.exception("Gesundheitsprüfung fehlgeschlagen")
            await asyncio.sleep(40)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(h.run()) for h in hubs.values()] + [asyncio.create_task(scheduler.run()), asyncio.create_task(energy_ha_loop()),
                                                                          asyncio.create_task(health_loop())]
        yield
        for t in tasks:
            t.cancel()
        energy.flush()
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

    confirm_pin = str(opts.get("confirm_pin") or "")
    if confirm_pin and len(confirm_pin) < 4:
        log.warning("confirm_pin hat weniger als 4 Zeichen – besser eine längere PIN wählen.")

    def require_pin(request: Request) -> None:
        """Sicherheits-PIN für kritische Aktionen (Option confirm_pin). Ohne die Option passiert nichts.
        428 = PIN fehlt (die PWA fragt sie ab und wiederholt), 403 = falsch (zählt), 429 = gesperrt."""
        if not confirm_pin:
            return
        ip = client_ip(request)
        wait = pin_limiter.wait_s(ip)
        if wait:
            raise HTTPException(status_code=429, detail="Zu viele falsche PINs.", headers={"Retry-After": str(wait)})
        given = request.headers.get("x-confirm-pin")
        if given is None:
            raise HTTPException(status_code=428, detail="PIN erforderlich")
        if not token_ok(confirm_pin, given):
            pin_limiter.fail(ip)
            record(request, "Falsche Sicherheits-PIN", detail=request.url.path[:80], ok=False)
            raise HTTPException(status_code=403, detail="PIN falsch")
        pin_limiter.ok(ip)

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

    @app.get("/api/energy", dependencies=[Depends(require_ui_token)])
    def energy_summary(days: int = 30, hub: Hub = Depends(get_hub)):
        """Strom und Kosten (Phase 10.6): nur gemessene GPU-/CPU-Leistung, also eine Untergrenze – siehe energy.py."""
        return energy.summary(hub.pc_id, price_ct, days)

    @app.get("/api/health-check", dependencies=[Depends(require_ui_token)])
    def health_check(hub: Hub = Depends(get_hub)):
        """Letzte Gesundheitsprüfung des Agenten (Phase 10.7), höchstens 5 Minuten alt; leer, solange noch keine vorliegt."""
        c = health_cache.get(hub.pc_id)
        return {"checked": c["at"], **c["data"]} if c else {"checked": None, "issues": [], "supported": "health" in hub.features}

    @app.get("/api/stats", dependencies=[Depends(require_ui_token)])
    def stats_summary(hub: Hub = Depends(get_hub)):
        """Statistik (Phase 10.7): Spielzeit pro Woche, Job-Dauer im Trend, Auslastung pro Tag – aus Strom- und Verlaufsdaten."""
        tz = energy.tz
        today = stats_mod.today_in(tz)
        since = time.time() - 90 * 86400
        games = [(n, t0, t1) for n, _tool, t0, t1, _wh in energy.events(hub.pc_id, "game", since)]
        jobs = energy.events(hub.pc_id, "job", since)
        return {"games_weekly": stats_mod.games_weekly(games, today, tz), "jobs": stats_mod.job_trend([(n, tool, t0, t1) for n, tool, t0, t1, _ in jobs]),
                "usage": stats_mod.usage_days(history.raw(hub.pc_id, 15), today, tz), "note": "Nur Läufe ab etwa 0,2 Wh Strom; Auslastung aus dem 14-Tage-Verlauf."}

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
        if op == "stop":
            require_pin(request)
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
        require_pin(request)
        return await relay(request, hub, "POST", f"/api/processes/{pid}/kill", what="Prozess beendet", detail=f"PID {pid}", timeout=20.0)

    @app.get("/api/gallery", dependencies=[Depends(require_ui_token)])
    async def gallery_list(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/gallery", params=take(request, GALLERY_PARAMS))

    @app.get("/api/gallery/thumb", dependencies=[Depends(require_ui_token)])
    async def gallery_thumb(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/gallery/thumb", params=take(request, GALLERY_PARAMS))

    # ---- Dateibrowser (Phase 10.9): nur lesen, wegen privater Dateien nur mit Schreibrecht, Downloads im Protokoll ----
    @app.get("/api/browse", dependencies=[Depends(require_write)])
    async def browse_list(request: Request, hub: Hub = Depends(get_hub)):
        return await relay(request, hub, "GET", "/api/browse", params=take(request, ("folder", "path")))

    @app.get("/api/browse/file", dependencies=[Depends(require_write)])
    async def browse_file(request: Request, hub: Hub = Depends(get_hub)):
        params = take(request, ("folder", "path", "download"))
        return await relay(request, hub, "GET", "/api/browse/file", params=params, what="Datei geladen",
                           detail=f"{params.get('folder', '')}/{params.get('path', '')}"[:200], timeout=120.0)

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

    @app.get("/api/guard", dependencies=[Depends(require_ui_token)])
    async def guard_check(request: Request, hub: Hub = Depends(get_hub)):
        """GPU-Konflikt-Wächter (Phase 10.1): Einschätzung des Agenten vor einem Spiel-/Programmstart (nur lesend)."""
        params = take(request, ("for", "id"))
        if params.get("for", "game") not in ("game", "program") or ("id" in params and params["id"] and not SAFE_ID.fullmatch(params["id"])):
            raise HTTPException(status_code=400, detail="ungültige Angabe")
        return await relay(request, hub, "GET", "/api/guard", params=params)

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

    def clean_name(value: str) -> str:
        return "".join(c for c in value if c.isprintable()).strip()[:80]

    @app.get("/api/steam/griddb/thumb/{gid}", dependencies=[Depends(require_ui_token)])
    async def steam_griddb_thumb(gid: int, request: Request, hub: Hub = Depends(get_hub)):
        if not 0 < gid < 2 ** 40:
            raise HTTPException(status_code=400, detail="ungültige ID")
        return await relay(request, hub, "GET", f"/api/steam/griddb/thumb/{gid}", timeout=20.0, cache="private, max-age=3600")

    @app.get("/api/steam/griddb/{appid}/{kind}", dependencies=[Depends(require_ui_token)])
    async def steam_griddb(appid: int, kind: str, request: Request, hub: Hub = Depends(get_hub)):
        if kind not in STEAM_KINDS:
            raise HTTPException(status_code=400, detail="ungültige Bildart")
        params = take(request, ("page", "nsfw"))
        if params.get("nsfw") not in (None, "true", "false"):
            raise HTTPException(status_code=400, detail="nsfw muss true oder false sein")
        return await relay(request, hub, "GET", f"/api/steam/griddb/{steam_appid(appid)}/{kind}", params=params, timeout=25.0)

    @app.put("/api/steam/art/{appid}/{kind}", dependencies=[Depends(require_write)])
    async def steam_art_set(appid: int, kind: str, request: Request, body: dict | None = Body(default=None), hub: Hub = Depends(get_hub)):
        if kind not in STEAM_KINDS:
            raise HTTPException(status_code=400, detail="ungültige Bildart")
        gid = (body or {}).get("griddb_id")
        if isinstance(gid, bool) or not isinstance(gid, int) or not 0 < gid < 2 ** 40:
            raise HTTPException(status_code=400, detail="griddb_id muss eine positive Ganzzahl sein")
        steam_appid(appid)
        return await relay(request, hub, "PUT", f"/api/steam/art/{appid}/{kind}", body={"griddb_id": gid},
                           what="Cover geändert", detail=f"{await steam_label(hub, appid)}: {kind}, SteamGridDB {gid}", timeout=40.0)

    @app.delete("/api/steam/art/{appid}/{kind}", dependencies=[Depends(require_write)])
    async def steam_art_reset(appid: int, kind: str, request: Request, hub: Hub = Depends(get_hub)):
        if kind not in STEAM_KINDS:
            raise HTTPException(status_code=400, detail="ungültige Bildart")
        steam_appid(appid)
        return await relay(request, hub, "DELETE", f"/api/steam/art/{appid}/{kind}", what="Cover zurückgesetzt",
                           detail=f"{await steam_label(hub, appid)}: {kind}")

    @app.post("/api/steam/games/{appid}/launch", dependencies=[Depends(require_write)])
    async def steam_launch(appid: int, request: Request, body: dict | None = Body(default=None), wake: bool = False, name: str = "",
                           hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        if wake and hub.status != "online":
            # Aufwecken und starten: Magic Packet senden (falls der PC noch aus ist), Spiel vormerken, der Hub startet es nach dem Hochfahren
            if hub.status == "offline":
                send_wake(hub)
            shown = clean_name(name) or f"AppID {appid}"
            hub.queue_launch(appid, shown)
            record(request, "Aufwecken und starten", pc=hub.name or hub.pc_id, detail=f"{shown} ({appid})")
            return JSONResponse({"pending": True, "appid": appid, "name": shown, "mode": hub.wake_mode}, status_code=202)
        force = bool((body or {}).get("force"))
        return await relay(request, hub, "POST", f"/api/steam/games/{appid}/launch", body={"force": force},
                           what="Spiel gestartet", detail=await steam_label(hub, appid), timeout=20.0)

    @app.delete("/api/steam/games/{appid}/launch", dependencies=[Depends(require_write)])
    async def steam_launch_cancel(appid: int, request: Request, hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        cancelled = hub.cancel_launch(appid)
        if cancelled:
            record(request, "Spielstart nach Aufwecken abgebrochen", pc=hub.name or hub.pc_id, detail=f"AppID {appid}")
        return {"ok": True, "cancelled": cancelled}

    @app.post("/api/steam/games/{appid}/update", dependencies=[Depends(require_write)])
    async def steam_update(appid: int, request: Request, then: str = "", name: str = "", hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        resp = await relay(request, hub, "POST", f"/api/steam/games/{appid}/update", what="Update angestoßen",
                           detail=await steam_label(hub, appid), timeout=20.0)
        if then == "launch" and resp.status_code < 300:
            shown = clean_name(name) or f"AppID {appid}"
            hub.queue_update_launch(appid, shown)
            record(request, "Update, danach starten", pc=hub.name or hub.pc_id, detail=f"{shown} ({appid})")
        return resp

    @app.delete("/api/steam/games/{appid}/update", dependencies=[Depends(require_write)])
    async def steam_update_cancel(appid: int, request: Request, hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        cancelled = hub.cancel_update_launch(appid)
        if cancelled:
            record(request, "Start nach Update abgebrochen", pc=hub.name or hub.pc_id, detail=f"AppID {appid}")
        return {"ok": True, "cancelled": cancelled}

    @app.post("/api/steam/games/{appid}/stop", dependencies=[Depends(require_write)])
    async def steam_stop(appid: int, request: Request, hub: Hub = Depends(get_hub)):
        steam_appid(appid)
        require_pin(request)
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

    def send_wake(hub: Hub) -> None:
        if not hub.opts.get("pc_mac"):
            raise HTTPException(status_code=400, detail="MAC-Adresse ist nicht konfiguriert")
        try:
            send_magic_packet(hub.opts["pc_mac"], hub.opts.get("broadcast_ip") or "255.255.255.255")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except OSError as e:
            raise HTTPException(status_code=502, detail=f"Senden fehlgeschlagen: {e}")
        hub.start_wake()

    @app.post("/api/wake", dependencies=[Depends(require_write)])
    def wake(request: Request, hub: Hub = Depends(get_hub)):
        send_wake(hub)
        record(request, "PC aufgeweckt", pc=hub.name or hub.pc_id)
        return {"ok": True, "status": hub.status}

    # ---- Szenen (Phase 10.2) ----
    scene_store = scenes_mod.SceneStore(data_dir / "scenes.json")
    scene_runner = scenes_mod.SceneRunner(ha, audit, send_wake)
    app_tasks: set = set()

    def scene_or_404(sid: str) -> dict:
        scene = scene_store.get(sid) if scenes_mod.SAFE_ID.fullmatch(sid) else None
        if not scene:
            raise HTTPException(status_code=404, detail="unbekannte Szene")
        return scene

    def scene_error(e: scenes_mod.SceneError):
        raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/scenes", dependencies=[Depends(require_ui_token)])
    def scenes_list():
        return {"scenes": scene_store.list(), "limits": {"max_scenes": scenes_mod.MAX_SCENES, "max_steps": scenes_mod.MAX_STEPS, "max_wait_s": scenes_mod.MAX_WAIT_S,
                                                          "actions": list(scenes_mod.SCENE_ACTIONS), "ha_configured": bool(ha.token)}}

    @app.post("/api/scenes", dependencies=[Depends(require_write)])
    def scene_create(request: Request, body: dict | None = Body(default=None)):
        try:
            scene = scene_store.create(body)
        except scenes_mod.SceneError as e:
            scene_error(e)
        record(request, "Szene angelegt", detail=scene["name"])
        return scene

    @app.put("/api/scenes/{sid}", dependencies=[Depends(require_write)])
    def scene_update(sid: str, request: Request, body: dict | None = Body(default=None)):
        scene_or_404(sid)
        try:
            scene = scene_store.replace(sid, body)
        except scenes_mod.SceneError as e:
            scene_error(e)
        record(request, "Szene geändert", detail=scene["name"])
        return scene

    @app.delete("/api/scenes/{sid}", dependencies=[Depends(require_write)])
    def scene_delete(sid: str, request: Request):
        scene = scene_or_404(sid)
        scene_store.delete(sid)
        record(request, "Szene gelöscht", detail=scene["name"])
        return {"ok": True}

    @app.post("/api/scenes/{sid}/run", dependencies=[Depends(require_write)])
    async def scene_run(sid: str, request: Request, hub: Hub = Depends(get_hub)):
        scene = scene_or_404(sid)
        if scenes_mod.is_critical(scene):
            require_pin(request)
        if scene.get("pc"):                                           # die Szene gehört zu einem bestimmten PC
            if scene["pc"] not in hubs:
                raise HTTPException(status_code=409, detail="Der PC dieser Szene ist nicht mehr eingerichtet")
            hub = hubs[scene["pc"]]
        try:
            scene_runner.start(hub, scene, who_label(getattr(request.state, "principal", None)))
        except scenes_mod.SceneError as e:
            raise HTTPException(status_code=409, detail=str(e))
        task = asyncio.create_task(scene_runner.run(hub, scene, who_label(getattr(request.state, "principal", None))))
        app_tasks.add(task)
        task.add_done_callback(app_tasks.discard)
        return JSONResponse({"started": True, "scene": scene["id"], "pc": hub.pc_id}, status_code=202)

    @app.post("/api/scenes/cancel", dependencies=[Depends(require_write)])
    async def scene_cancel(request: Request, hub: Hub = Depends(get_hub)):
        cancelled = await scene_runner.cancel(hub)
        if cancelled:
            record(request, "Szene abgebrochen (angefordert)", pc=hub.name or hub.pc_id, detail=hub.scene_run["name"])
        return {"ok": True, "cancelled": cancelled}

    # ---- Zeitpläne (Phase 10.5) ----
    schedule_store = schedules_mod.ScheduleStore(data_dir / "schedules.json")
    scheduler = schedules_mod.Scheduler(schedule_store, hubs, scene_store, scene_runner, audit, send_wake,
                                        now=lambda: datetime.now(tz) if tz else datetime.now().astimezone())

    def schedule_or_404(sid: str) -> dict:
        s = schedule_store.get(sid) if schedules_mod.SAFE_ID.fullmatch(sid) else None
        if not s:
            raise HTTPException(status_code=404, detail="unbekannter Zeitplan")
        return s

    def schedule_public(s: dict) -> dict:
        return {**s, "text": schedules_mod.describe(s), "next": schedules_mod.next_run_date(s, scheduler.now()).isoformat() if s["enabled"] else None}

    @app.get("/api/schedules", dependencies=[Depends(require_ui_token)])
    def schedules_list():
        return {"schedules": [schedule_public(s) for s in schedule_store.list()], "timezone": str(tz) if tz else "lokal", "now": scheduler.now().isoformat(timespec="minutes"),
                "limits": {"max": schedules_mod.MAX_SCHEDULES}}

    @app.post("/api/schedules", dependencies=[Depends(require_write)])
    def schedule_create(request: Request, body: dict | None = Body(default=None)):
        try:
            cand = schedules_mod.clean_schedule(body)
            if schedules_mod.is_critical(cand):
                require_pin(request)
            s = schedule_store.create(body)
        except schedules_mod.ScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e))
        record(request, "Zeitplan angelegt", detail=schedules_mod.describe(s)[:120])
        return schedule_public(s)

    @app.put("/api/schedules/{sid}", dependencies=[Depends(require_write)])
    def schedule_update(sid: str, request: Request, body: dict | None = Body(default=None)):
        old = schedule_or_404(sid)
        try:
            cand = schedules_mod.clean_schedule(body, sid)
            if schedules_mod.is_critical(cand) or schedules_mod.is_critical(old):
                require_pin(request)
            s = schedule_store.replace(sid, body)
        except schedules_mod.ScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e))
        record(request, "Zeitplan geändert", detail=schedules_mod.describe(s)[:120])
        return schedule_public(s)

    @app.delete("/api/schedules/{sid}", dependencies=[Depends(require_write)])
    def schedule_delete(sid: str, request: Request):
        s = schedule_or_404(sid)
        schedule_store.delete(sid)
        record(request, "Zeitplan gelöscht", detail=s["name"])
        return {"ok": True}

    @app.post("/api/schedules/{sid}/skip", dependencies=[Depends(require_write)])
    def schedule_skip(sid: str, request: Request):
        schedule_or_404(sid)
        d = scheduler.skip_next(sid)
        record(request, "Zeitplan: nächsten Lauf überspringen", detail=f"{schedule_store.get(sid)['name']} ({d})")
        return {"ok": True, "skip_date": d}

    @app.delete("/api/schedules/{sid}/skip", dependencies=[Depends(require_write)])
    def schedule_unskip(sid: str):
        schedule_or_404(sid)
        scheduler.unskip(sid)
        return {"ok": True}

    @app.post("/api/action/{name}", dependencies=[Depends(require_write)])
    async def action(name: str, request: Request, body: dict | None = Body(default=None), hub: Hub = Depends(get_hub)):
        if name not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=404, detail="unbekannte Aktion")
        if name in CRITICAL_ACTIONS:
            require_pin(request)
        if hub.status != "online":
            raise HTTPException(status_code=409, detail="PC ist nicht online")
        code, data = await hub.agent_action(name, body)
        if code == 200 and name in ("shutdown", "sleep", "standby", "restart"):
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
