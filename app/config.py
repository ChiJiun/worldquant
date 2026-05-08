from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip().lstrip("\ufeff")] = value.strip()


def as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def as_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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
    rate_limit_seconds: float
    sharpe_threshold: float
    fitness_threshold: float
    dry_run: bool
    max_poll_attempts: int
    poll_interval_seconds: float
    batch_size: int
    population_size: int
    elite_count: int
    immigrant_ratio: float
    mutation_rate: float
    crossover_rate: float
    generations: int
    mine_cycles: int
    mine_sleep_seconds: float
    seed_history_limit: int
    template_whitelist: List[str]
    template_blacklist: List[str]
    checkpoint_every_cycles: int
    storage_path: Path
    output_dir: Path
    log_dir: Path
    fields_config: Path
    template_config: Path
    client_mode: str

    @classmethod
    def load(cls, root: Optional[Path] = None) -> "Settings":
        root = root or Path.cwd()
        load_dotenv(root / ".env")
        output_dir = Path(os.getenv("WQ_OUTPUT_DIR", "outputs"))
        log_dir = Path(os.getenv("WQ_LOG_DIR", "logs"))
        storage_path = Path(os.getenv("WQ_STORAGE_PATH", "data/worldquant.db"))
        fields_config = Path(os.getenv("WQ_FIELDS_CONFIG", "config/fields.json"))
        template_config = Path(os.getenv("WQ_TEMPLATE_CONFIG", "config/templates.json"))
        return cls(
            username=os.getenv("WQ_USERNAME", ""),
            password=os.getenv("WQ_PASSWORD", ""),
            api_base_url=os.getenv("WQ_API_BASE_URL", "https://api.worldquantbrain.com"),
            api_login_path=os.getenv("WQ_API_LOGIN_PATH", "/authentication"),
            api_simulate_path=os.getenv("WQ_API_SIMULATE_PATH", "/simulations"),
            api_status_path=os.getenv("WQ_API_STATUS_PATH", "/simulations/{simulation_id}"),
            api_result_path=os.getenv("WQ_API_RESULT_PATH", "/simulations/{simulation_id}/result"),
            auth_mode=os.getenv("WQ_AUTH_MODE", "auto"),
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
            rate_limit_seconds=float(os.getenv("WQ_RATE_LIMIT_SECONDS", "1.0")),
            sharpe_threshold=float(os.getenv("WQ_SHARPE_THRESHOLD", "1.25")),
            fitness_threshold=float(os.getenv("WQ_FITNESS_THRESHOLD", "1.0")),
            dry_run=as_bool(os.getenv("WQ_DRY_RUN", "true"), default=True),
            max_poll_attempts=int(os.getenv("WQ_MAX_POLL_ATTEMPTS", "20")),
            poll_interval_seconds=float(os.getenv("WQ_POLL_INTERVAL_SECONDS", "3.0")),
            batch_size=int(os.getenv("WQ_BATCH_SIZE", "5")),
            population_size=int(os.getenv("WQ_POPULATION_SIZE", "12")),
            elite_count=int(os.getenv("WQ_ELITE_COUNT", "3")),
            immigrant_ratio=float(os.getenv("WQ_IMMIGRANT_RATIO", "0.2")),
            mutation_rate=float(os.getenv("WQ_MUTATION_RATE", "0.35")),
            crossover_rate=float(os.getenv("WQ_CROSSOVER_RATE", "0.7")),
            generations=int(os.getenv("WQ_GENERATIONS", "3")),
            mine_cycles=int(os.getenv("WQ_MINE_CYCLES", "1")),
            mine_sleep_seconds=float(os.getenv("WQ_MINE_SLEEP_SECONDS", "5.0")),
            seed_history_limit=int(os.getenv("WQ_SEED_HISTORY_LIMIT", "12")),
            template_whitelist=as_list(os.getenv("WQ_TEMPLATE_WHITELIST")),
            template_blacklist=as_list(os.getenv("WQ_TEMPLATE_BLACKLIST")),
            checkpoint_every_cycles=int(os.getenv("WQ_CHECKPOINT_EVERY_CYCLES", "5")),
            storage_path=storage_path,
            output_dir=output_dir,
            log_dir=log_dir,
            fields_config=fields_config,
            template_config=template_config,
            client_mode=os.getenv("WQ_CLIENT_MODE", "auto"),
        )

    def ensure_directories(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def load_fields(self) -> Dict[str, Any]:
        return json.loads(self.fields_config.read_text(encoding="utf-8"))

    def load_template_specs(self) -> Dict[str, Any]:
        specs = json.loads(self.template_config.read_text(encoding="utf-8"))
        if self.template_whitelist:
            specs = {name: spec for name, spec in specs.items() if name in self.template_whitelist}
        if self.template_blacklist:
            specs = {name: spec for name, spec in specs.items() if name not in self.template_blacklist}
        return specs

    def simulation_settings_payload(self) -> Dict[str, Any]:
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
