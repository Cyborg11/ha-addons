"""Anmeldung der Weboberfläche: PIN -> Gerätetoken, QR-Kopplung, Sperre nach Fehlversuchen.

Geräte bekommen ein langes Zufallstoken; gespeichert wird nur dessen SHA-256 (``devices.json`` im Datenordner
des Add-ons). Die PIN selbst landet nie im Browser.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from pathlib import Path

log = logging.getLogger("pc-companion-hub")

MAX_DEVICES = 20
ROLES = ("full", "view")   # view = nur ansehen (Wanddisplay, Familie)
PAIR_TTL_S = 300          # QR-Code ist 5 Minuten gültig, einmal einlösbar
MAX_PAIR_CODES = 10
LOCK_AFTER = 5            # Fehlversuche je Client-IP ...
LOCK_S = 900              # ... dann 15 Minuten Sperre
GLOBAL_LIMIT = 100        # Fehlversuche insgesamt pro Stunde ...
GLOBAL_LOCK_S = 3600      # ... dann sperrt der Hub die Anmeldung 1 Stunde für alle
LAST_SEEN_STEP_S = 60


def now() -> float:
    return time.time()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secret_matches(expected: str, given: str | None) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(expected.encode(), given.encode())


def clean_name(name, fallback: str = "Gerät") -> str:
    text = re.sub(r"[\x00-\x1f\x7f<>]", "", str(name or "")).strip()[:60]
    return text or fallback


def device_name_from_ua(ua: str | None) -> str:
    """Grober, lesbarer Gerätename aus dem User-Agent (nur zur Anzeige)."""
    ua = ua or ""
    for needle, label in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                          ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")):
        if needle in ua:
            os_name = label
            break
    else:
        os_name = "Gerät"
    for needle, label in (("Firefox", "Firefox"), ("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome", "Chrome"), ("Safari", "Safari")):
        if needle in ua:
            return f"{os_name} ({label})"
    return os_name


class DeviceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.devices: list[dict] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.devices = [d for d in data.get("devices", []) if {"id", "hash"} <= set(d)]
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("devices.json nicht lesbar (%s) – starte ohne gekoppelte Geräte", e)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"devices": self.devices}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            log.warning("devices.json nicht schreibbar (%s) – Kopplungen gehen beim Neustart verloren", e)

    def create(self, name: str, role: str = "full") -> tuple[dict, str]:
        token = secrets.token_urlsafe(32)
        t = now()
        dev = {"id": secrets.token_hex(4), "name": clean_name(name), "role": role if role in ROLES else "full",
               "hash": hash_token(token), "created": t, "last_seen": t}
        self.devices.append(dev)
        if len(self.devices) > MAX_DEVICES:      # das am längsten ungenutzte Gerät fliegt raus
            self.devices.sort(key=lambda d: d.get("last_seen", 0))
            self.devices = self.devices[len(self.devices) - MAX_DEVICES:]
        self._save()
        return self.public_one(dev), token

    def verify(self, token: str | None) -> dict | None:
        if not token:
            return None
        h = hash_token(token)
        found = None
        for dev in self.devices:                 # kein vorzeitiger Abbruch: gleichbleibende Laufzeit
            if hmac.compare_digest(dev["hash"], h):
                found = dev
        if found and now() - found.get("last_seen", 0) >= LAST_SEEN_STEP_S:
            found["last_seen"] = now()
            self._save()
        return found

    def set_role(self, device_id: str, role: str) -> bool:
        if role not in ROLES:
            return False
        for dev in self.devices:
            if dev["id"] == device_id:
                dev["role"] = role
                self._save()
                return True
        return False

    def get(self, device_id: str) -> dict | None:
        return next((d for d in self.devices if d["id"] == device_id), None)

    def revoke(self, device_id: str) -> bool:
        before = len(self.devices)
        self.devices = [d for d in self.devices if d["id"] != device_id]
        if len(self.devices) != before:
            self._save()
            return True
        return False

    @staticmethod
    def public_one(dev: dict) -> dict:
        return {"id": dev["id"], "name": dev.get("name", "Gerät"), "role": dev.get("role", "full"),
                "created": dev.get("created"), "last_seen": dev.get("last_seen")}

    def public(self) -> list[dict]:
        return [self.public_one(d) for d in sorted(self.devices, key=lambda d: -d.get("last_seen", 0))]


class Pairing:
    """Einmalige, kurzlebige Kopplungscodes (nur im Speicher)."""

    def __init__(self):
        self.codes: dict[str, tuple[float, str]] = {}    # code -> (gültig bis, Rolle)

    def _prune(self) -> None:
        t = now()
        self.codes = {c: v for c, v in self.codes.items() if v[0] > t}

    def create(self, role: str = "full") -> str:
        self._prune()
        while len(self.codes) >= MAX_PAIR_CODES:
            self.codes.pop(min(self.codes, key=lambda c: self.codes[c][0]))
        code = secrets.token_urlsafe(18)
        self.codes[code] = (now() + PAIR_TTL_S, role if role in ROLES else "full")
        return code

    def redeem(self, code: str | None) -> str | None:
        """Gibt die Rolle des Codes zurück (und entwertet ihn) oder None."""
        self._prune()
        entry = self.codes.pop(code, None) if code else None
        return entry[1] if entry else None


class Limiter:
    """Sperrt Anmeldeversuche nach Fehlschlägen: je Client-IP und insgesamt."""

    def __init__(self):
        self.ips: dict[str, list[float]] = {}     # ip -> [fehler, gesperrt_bis]
        self.recent: list[float] = []              # Zeitpunkte der letzten Fehlversuche
        self.global_until = 0.0

    def wait_s(self, ip: str) -> int:
        """Sekunden bis zur nächsten erlaubten Anmeldung (0 = erlaubt)."""
        t = now()
        until = max(self.global_until, self.ips.get(ip, [0, 0])[1])
        return max(0, int(until - t) + 1) if until > t else 0

    def fail(self, ip: str) -> None:
        t = now()
        if len(self.ips) > 1000:
            self.ips = {k: v for k, v in self.ips.items() if v[1] > t}
        entry = self.ips.setdefault(ip, [0, 0.0])
        entry[0] += 1
        if entry[0] >= LOCK_AFTER:
            entry[0], entry[1] = 0, t + LOCK_S
        self.recent = [x for x in self.recent if x > t - 3600] + [t]
        if len(self.recent) >= GLOBAL_LIMIT:
            self.global_until, self.recent = t + GLOBAL_LOCK_S, []
            log.warning("Sehr viele fehlgeschlagene Anmeldungen – Anmeldung für 1 Stunde gesperrt.")

    def ok(self, ip: str) -> None:
        self.ips.pop(ip, None)
