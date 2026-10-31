"""
Log persistente del cliente (Windows/Linux).

- Archivo: <dir>/CiberMondayClient.log (+ .old al rotar)
- Opcional: tee de stdout/stderr al archivo
- tail() para /api/logs del diagnostic
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from typing import Optional

LOG_FILENAME = "CiberMondayClient.log"
LOG_MAX_BYTES = 5 * 1024 * 1024

_lock = threading.Lock()
_log_path: Optional[str] = None
_tee_installed = False


class _Tee:
    def __init__(self, stream, path: str):
        self._stream = stream
        self._path = path

    def write(self, data):
        try:
            if self._stream is not None:
                self._stream.write(data)
                self._stream.flush()
        except Exception:
            pass
        if not data:
            return
        try:
            path = _log_path or self._path
            _append_raw(path, data if isinstance(data, str) else data.decode("utf-8", "replace"))
        except Exception:
            pass

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass

    def fileno(self):
        return self._stream.fileno()

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False


def log_path() -> Optional[str]:
    return _log_path


def setup_client_logging(directory: str, tee: bool = True) -> str:
    """Configura ruta de log y, si tee=True, duplica stdout/stderr al archivo."""
    global _log_path, _tee_installed
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, LOG_FILENAME)
    _log_path = path
    _rotate_if_needed(path)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(
                f"\n{'=' * 60}\n"
                f"[Log] session {datetime.now().isoformat(timespec='seconds')}\n"
                f"{'=' * 60}\n"
            )
    except Exception:
        pass
    if tee and not _tee_installed:
        try:
            sys.stdout = _Tee(sys.stdout, path)  # type: ignore
            sys.stderr = _Tee(sys.stderr, path)  # type: ignore
            _tee_installed = True
        except Exception:
            pass
    return path


def _rotate_if_needed(path: str) -> None:
    try:
        if os.path.isfile(path) and os.path.getsize(path) > LOG_MAX_BYTES:
            bak = path + ".old"
            if os.path.isfile(bak):
                os.remove(bak)
            os.rename(path, bak)
    except Exception:
        pass


def _append_raw(path: str, data: str) -> None:
    with _lock:
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(data)


def append_line(message: str) -> None:
    path = _log_path
    if not path:
        return
    line = message if message.endswith("\n") else message + "\n"
    try:
        _append_raw(path, line)
    except Exception:
        pass


def tail_lines(n: int = 100, path: Optional[str] = None) -> list[str]:
    """Últimas n líneas del log (mejor esfuerzo)."""
    target = path or _log_path
    if not target or not os.path.isfile(target):
        return []
    try:
        n = max(1, min(int(n), 2000))
    except Exception:
        n = 100
    try:
        with open(target, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            return lines[-n:]
    except Exception:
        return []
