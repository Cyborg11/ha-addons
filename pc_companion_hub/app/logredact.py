"""Zugriffsprotokoll ohne Anmelde-Token: uvicorn schreibt die Adresse der WebSocket-Verbindung (``/ws?token=...``) ins Log.

Das Geräte-Token stünde sonst im Klartext im Add-on-Protokoll von Home Assistant (wird gern in Fehlerberichten geteilt)."""
from __future__ import annotations

import logging
import re

_TOKEN_IN_URL = re.compile(r"([?&]token=)[^&\s\"']+", re.IGNORECASE)


def redact(text: str) -> str:
    return _TOKEN_IN_URL.sub(r"\1***", text)


class RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, RedactTokenFilter) for f in lg.filters):
            lg.addFilter(RedactTokenFilter())
