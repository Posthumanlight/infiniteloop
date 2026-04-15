import logging
import os
from datetime import datetime
from collections import deque
from typing import List, Dict, Any, Optional
from pythonjsonlogger.json import JsonFormatter as JsonFormatter


class CircularBufferHandler(logging.Handler):
    """In-memory circular buffer for recent logs."""

    def __init__(self, max_size: int = 1000):
        super().__init__()
        self.buffer: deque = deque(maxlen=max_size)

    def emit(self, record: logging.LogRecord):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "user_id": getattr(record, "user_id", None),
            "message_type": getattr(record, "message_type", None),
        }
        self.buffer.append(log_entry)

    def get_logs(
        self,
        limit: int = 100,
        level_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        logs = list(self.buffer)

        if level_filter:
            logs = [log for log in logs if log["level"] == level_filter.upper()]

        return logs[-limit:]


def setup_telegram_logging(
    name: str = "telegram_bot"
) -> tuple[logging.Logger, CircularBufferHandler]:
    """
    Setup structured JSON logger with:
    - File handler
    - Console fallback
    - Circular buffer for dashboard
    """

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # prevent double logging via root

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger, next(
            (h for h in logger.handlers if isinstance(h, CircularBufferHandler)),
            None
        )

    # JSON formatter
    formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(user_id)s %(message_type)s"
    )

    # Try file handler
    try:
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)

        file_path = os.path.join(logs_dir, "telegram_bot.log")
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        logger.addHandler(file_handler)

    except Exception:
        pass

    # Завжди додаємо вивід у консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    # Circular buffer handler
    buffer_handler = CircularBufferHandler(max_size=1000)
    buffer_handler.setLevel(logging.DEBUG)
    logger.addHandler(buffer_handler)

    return logger, buffer_handler