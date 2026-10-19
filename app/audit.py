"""Layer 8 - audit log: one JSON line per grade edit and per 403. Never logs secrets."""
import json
import sys
import threading
from datetime import datetime, timezone

_SENSITIVE = ("password", "token", "secret", "authorization")


class AuditLogger:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def log(self, actor_id, action, resource, result, **extra):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "actorId": actor_id,
            "action": action,
            "resource": resource,
            "result": result,
        }
        for k, v in extra.items():
            if not any(s in k.lower() for s in _SENSITIVE):
                entry[k] = v
        line = json.dumps(entry, ensure_ascii=False)
        try:
            with self._lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:  # auditing problems must not leak details to clients
            print(f"[audit] cannot write {self.path}: {exc}", file=sys.stderr)


class _NullLogger:
    def log(self, *args, **kwargs):
        pass


_current = _NullLogger()


def configure(logger):
    global _current
    _current = logger


def get():
    return _current
