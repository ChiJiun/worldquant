from pathlib import Path

import pytest
import json

from app.config import Settings
from app.templates import TemplateEngine


TEST_TEMPLATE_SPECS = {
    "mean_reversion": {"fields": ["close", "vwap", "returns"], "windows": [5, 10, 20, 40], "wrappers": ["rank", "zscore"]},
    "momentum": {"fields": ["close", "returns", "vwap"], "windows": [10, 20, 60, 120], "wrappers": ["rank", "ts_rank"]},
    "price_volume_divergence": {"fields": ["close", "vwap", "volume", "adv20"], "windows": [5, 10, 20, 60], "wrappers": ["rank", "zscore", "ts_decay_linear"]},
    "fundamental_cross": {"fields": ["eps", "operating_margin", "sales", "book_value", "cashflow"], "windows": [20, 60, 120], "wrappers": ["rank", "zscore"]},
    "volatility_reversion": {"fields": ["returns", "close", "vwap"], "windows": [10, 20, 40, 60], "wrappers": ["rank", "zscore", "ts_rank"]},
    "breakout": {"fields": ["close", "high", "low", "vwap"], "windows": [20, 40, 60, 120], "wrappers": ["rank", "ts_rank"]},
    "quality_value": {"fields": ["book_value", "cashflow", "sales", "operating_margin", "eps"], "windows": [20, 60, 120], "wrappers": ["rank", "zscore"]},
    "acceleration": {"fields": ["close", "returns", "vwap"], "windows": [5, 10, 20, 40], "wrappers": ["rank", "zscore", "ts_rank"]},
    "range_reversion": {"fields": ["close", "high", "low", "vwap"], "windows": [10, 20, 40, 60], "wrappers": ["rank", "zscore"]},
    "quality_efficiency": {"fields": ["sales", "cashflow", "operating_margin", "eps"], "windows": [20, 60, 120], "wrappers": ["rank", "zscore", "ts_rank"]},
    "volume_confirmed_breakout": {"fields": ["close", "high", "low", "vwap", "volume", "adv20", "adv60"], "windows": [10, 20, 40, 60], "wrappers": ["rank", "zscore", "ts_rank"]},
    "liquidity_reversal": {"fields": ["close", "vwap", "returns", "volume", "adv20", "adv60"], "windows": [5, 10, 20, 40], "wrappers": ["rank", "zscore"]},
    "fundamental_momentum_spread": {"fields": ["close", "returns", "vwap", "eps", "operating_margin", "sales", "book_value", "cashflow"], "windows": [10, 20, 60, 120], "wrappers": ["rank", "zscore", "ts_rank"]},
}


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    template_config = tmp_path / "config" / "templates.json"
    template_config.parent.mkdir(parents=True, exist_ok=True)
    template_config.write_text(json.dumps(TEST_TEMPLATE_SPECS), encoding="utf-8")
    return Settings(
        username="user",
        password="pass",
        api_base_url="https://example.com",
        api_login_path="/login",
        api_simulate_path="/simulate",
        api_status_path="/simulate/{simulation_id}",
        api_result_path="/simulate/{simulation_id}/result",
        auth_mode="auto",
        simulation_type="REGULAR",
        instrument_type="EQUITY",
        region="USA",
        universe="TOP3000",
        delay=1,
        decay=0,
        neutralization="INDUSTRY",
        truncation=0.08,
        pasteurization="ON",
        unit_handling="VERIFY",
        nan_handling="OFF",
        language="FASTEXPR",
        visualization=False,
        rate_limit_seconds=0.0,
        sharpe_threshold=1.25,
        fitness_threshold=1.0,
        dry_run=True,
        max_poll_attempts=3,
        poll_interval_seconds=0.0,
        batch_size=4,
        population_size=6,
        elite_count=2,
        immigrant_ratio=0.25,
        mutation_rate=0.4,
        crossover_rate=0.7,
        generations=2,
        mine_cycles=2,
        mine_sleep_seconds=0.0,
        seed_history_limit=6,
        template_whitelist=[],
        template_blacklist=[],
        checkpoint_every_cycles=1,
        storage_path=tmp_path / "data" / "test.db",
        output_dir=tmp_path / "outputs",
        log_dir=tmp_path / "logs",
        fields_config=Path("config/fields.json"),
        template_config=template_config,
        client_mode="mock",
    )


@pytest.fixture()
def template_engine(settings: Settings) -> TemplateEngine:
    return TemplateEngine(settings.load_fields(), settings.load_template_specs())
