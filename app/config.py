from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import os


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip())


def as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    username: str
    password: str
    api_base_url: str
    api_login_path: str
    api_simulate_path: str
    api_status_path: str
    api_result_path: str
    auth_mode: str
    client_mode: str
    dry_run: bool
    request_timeout_seconds: float
    rate_limit_seconds: float
    max_poll_attempts: int
    poll_interval_seconds: float
    simulation_type: str
    instrument_type: str
    region: str
    universe: str
    delay: int
    decay: int
    neutralization: str
    truncation: float
    pasteurization: str
    unit_handling: str
    nan_handling: str
    language: str
    visualization: bool
    candidate_file: Path
    output_dir: Path
    research_dir: Path
    log_dir: Path
    fields_config: Path

    @classmethod
    def load(cls, root: Optional[Path] = None) -> "Settings":
        root = root or Path.cwd()
        load_dotenv(root / ".env")
        return cls(
            username=os.getenv("WQ_USERNAME", ""),
            password=os.getenv("WQ_PASSWORD", ""),
            api_base_url=os.getenv("WQ_API_BASE_URL", "https://api.worldquantbrain.com").rstrip("/"),
            api_login_path=os.getenv("WQ_API_LOGIN_PATH", "/authentication"),
            api_simulate_path=os.getenv("WQ_API_SIMULATE_PATH", "/simulations"),
            api_status_path=os.getenv("WQ_API_STATUS_PATH", "/simulations/{simulation_id}"),
            api_result_path=os.getenv("WQ_API_RESULT_PATH", "/simulations/{simulation_id}/result"),
            auth_mode=os.getenv("WQ_AUTH_MODE", "auto"),
            client_mode=os.getenv("WQ_CLIENT_MODE", "requests"),
            dry_run=as_bool(os.getenv("WQ_DRY_RUN", "true"), default=True),
            request_timeout_seconds=float(os.getenv("WQ_REQUEST_TIMEOUT_SECONDS", "60")),
            rate_limit_seconds=float(os.getenv("WQ_RATE_LIMIT_SECONDS", "2.0")),
            max_poll_attempts=int(os.getenv("WQ_MAX_POLL_ATTEMPTS", "120")),
            poll_interval_seconds=float(os.getenv("WQ_POLL_INTERVAL_SECONDS", "5.0")),
            simulation_type=os.getenv("WQ_SIMULATION_TYPE", "REGULAR"),
            instrument_type=os.getenv("WQ_INSTRUMENT_TYPE", "EQUITY"),
            region=os.getenv("WQ_REGION", "USA"),
            universe=os.getenv("WQ_UNIVERSE", "TOP3000"),
            delay=int(os.getenv("WQ_DELAY", "1")),
            decay=int(os.getenv("WQ_DECAY", "0")),
            neutralization=os.getenv("WQ_NEUTRALIZATION", "INDUSTRY"),
            truncation=float(os.getenv("WQ_TRUNCATION", "0.08")),
            pasteurization=os.getenv("WQ_PASTEURIZATION", "ON"),
            unit_handling=os.getenv("WQ_UNIT_HANDLING", "VERIFY"),
            nan_handling=os.getenv("WQ_NAN_HANDLING", "OFF"),
            language=os.getenv("WQ_LANGUAGE", "FASTEXPR"),
            visualization=as_bool(os.getenv("WQ_VISUALIZATION", "false"), default=False),
            candidate_file=Path(os.getenv("WQ_CANDIDATE_FILE", "data/candidates.jsonl")),
            output_dir=Path(os.getenv("WQ_OUTPUT_DIR", "outputs")),
            research_dir=Path(os.getenv("WQ_RESEARCH_DIR", "research")),
            log_dir=Path(os.getenv("WQ_LOG_DIR", "logs")),
            fields_config=Path(os.getenv("WQ_FIELDS_CONFIG", "config/fields.json")),
        )

    def ensure_directories(self) -> None:
        self.candidate_file.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "runs").mkdir(parents=True, exist_ok=True)
        self.research_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def simulation_settings_payload(self) -> dict:
        return {
            "instrumentType": self.instrument_type,
            "region": self.region,
            "universe": self.universe,
            "delay": self.delay,
            "decay": self.decay,
            "neutralization": self.neutralization,
            "truncation": self.truncation,
            "pasteurization": self.pasteurization,
            "unitHandling": self.unit_handling,
            "nanHandling": self.nan_handling,
            "language": self.language,
            "visualization": self.visualization,
        }
