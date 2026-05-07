from __future__ import annotations

from pathlib import Path
import logging


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    event_handler = logging.FileHandler(log_dir / "events.log", encoding="utf-8")
    event_handler.setFormatter(formatter)
    event_handler.setLevel(logging.INFO)
    logging.getLogger("events").addHandler(event_handler)
    logging.getLogger("events").setLevel(logging.INFO)
