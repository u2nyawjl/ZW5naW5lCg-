import json
import os
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class Level(StrEnum):
    INFO = "info"
    WARN = "warn"
    ALERT = "alert"
    CRITICAL = "critical"    # honeypot, malware confirmado


def log_event(
    event_type: str,
    message: str,
    level: Level = Level.INFO,
    logs_dir: Path | None = None,
    **fields: Any,
) -> dict:
    """Append-only JSONL: una línea por evento. Es la fuente del timeline del dashboard."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "type": event_type,
        "level": str(level),
        "message": message,
        **fields,
    }

    target = logs_dir or Path(os.getenv("LOGS_DIR", "/app/logs"))
    target.mkdir(parents=True, exist_ok=True)
    with open(target / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    return event
