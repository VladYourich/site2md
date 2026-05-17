import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("job_id", "url", "stage", "error"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)
        if record.exc_info and record.exc_info[1]:
            log_entry["exc_text"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger("scrapy").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
