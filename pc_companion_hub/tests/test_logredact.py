import logging

from app import logredact


def test_token_is_removed_from_access_log_lines():
    assert logredact.redact("/ws?token=abc123-_x&pc=ki") == "/ws?token=***&pc=ki"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "WebSocket", "/ws?token=geheim123&pc=a", "1.1", 403), None)
    logredact.RedactTokenFilter().filter(rec)
    assert "geheim123" not in rec.getMessage() and "token=***" in rec.getMessage() and "pc=a" in rec.getMessage()


def test_filter_is_installed_once_on_the_uvicorn_loggers():
    logredact.install()
    logredact.install()
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        assert sum(isinstance(f, logredact.RedactTokenFilter) for f in logging.getLogger(name).filters) == 1
