import json
import threading
from datetime import datetime, timezone
from pathlib import Path


_path: str | Path = "audit.log"
_lock = threading.Lock()


def configure(path: str | Path) -> None:
    global _path
    _path = path


def record(
    actor_id: str | None,
    action: str,
    resource: str,
    result: str,
    *,
    path: str | Path | None = None,
    **extra: object,
) -> None:
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actorId": actor_id,
        "action": action,
        "resource": resource,
        "result": result,
        **extra,
    }
    with _lock, open(path if path is not None else _path, "a", encoding="utf-8") as file:
        file.write(json.dumps(line) + "\n")
