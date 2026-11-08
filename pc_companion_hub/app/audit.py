"""Protokoll der Aktionen (JSON-Zeilen in /data/audit.log, begrenzt)."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("pc-companion-hub")

MAX_LINES = 1000
SHRINK_AT = 1300           # erst bei so vielen Zeilen kürzen, damit nicht bei jedem Eintrag neu geschrieben wird


def now() -> float:
    return time.time()


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._count = None

    def _lines(self) -> list[str]:
        try:
            return self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError as e:
            log.warning("audit.log nicht lesbar: %s", e)
            return []

    def add(self, who: str, what: str, pc: str | None = None, detail: str | None = None, ok: bool = True) -> None:
        entry = {"t": round(now(), 1), "who": who[:60], "what": what[:60], "ok": bool(ok)}
        if pc:
            entry["pc"] = pc[:60]
        if detail:
            entry["detail"] = detail[:160]
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self._count is None:
                    self._count = len(self._lines())
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._count += 1
                if self._count > SHRINK_AT:
                    keep = self._lines()[-MAX_LINES:]
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
                    tmp.replace(self.path)
                    self._count = len(keep)
            except OSError as e:
                log.warning("audit.log nicht schreibbar: %s", e)

    def tail(self, limit: int = 50) -> list[dict]:
        """Neueste Einträge zuerst."""
        out = []
        for line in reversed(self._lines()[-max(1, min(limit, MAX_LINES)):]):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
