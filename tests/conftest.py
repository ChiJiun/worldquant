from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        username="user",
        password="pass",
        api_base_url="https://example.com",
        api_login_path="/authentication",
        api_simulate_path="/simulations",
        api_status_path="/simulations/{simulation_id}",
        api_result_path="/simulations/{simulation_id}/result",
        auth_mode="auto",
        client_mode="mock",
        dry_run=True,
        request_timeout_seconds=1.0,
        rate_limit_seconds=0.0,
        max_poll_attempts=3,
        poll_interval_seconds=0.0,
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
        candidate_file=tmp_path / "data" / "candidates.jsonl",
        output_dir=tmp_path / "outputs",
        log_dir=tmp_path / "logs",
        fields_config=Path("config/fields.json"),
    )
