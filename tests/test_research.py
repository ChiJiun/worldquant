import json

from app.research import initialize_research_dir, record_research_artifacts
from app.research_paths import research_paths


def test_research_artifacts_record_validation_candidate(tmp_path):
    research_dir = tmp_path / "research"
    initialize_research_dir(research_dir)
    paths = research_paths(research_dir)

    record_research_artifacts(
        research_dir,
        [
            {
                "recorded_at": "2026-05-09T00:00:00Z",
                "candidate_id": "C_pass",
                "family": "long_horizon_zscore_plus_close_location_ensemble",
                "expression": "zscore(-ts_decay_linear(((returns - ts_mean(returns, 120)) / (1 + ts_std_dev(returns, 120))), 100)) + zscore(-ts_decay_linear(((close - low) / (high - low)), 10))",
                "result_id": "alpha-1",
                "metrics": {
                    "sharpe": 1.65,
                    "fitness": 1.1,
                    "returns": 0.1972,
                    "drawdown": 0.1023,
                    "turnover": 0.4415,
                    "checks_failed": 0,
                },
            }
        ],
        [],
    )

    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    family = memory["families"]["long_horizon_zscore_plus_close_location_ensemble"]
    assert family["status"] == "candidate_validation"
    assert family["workflow_loop"] == "pass_alpha_improvement_loop"
    assert family["best_candidate"]["candidate_id"] == "C_pass"
    assert memory["global_best"]["candidate_id"] == "C_pass"

    decisions = paths.experiment_decisions.read_text(encoding="utf-8").splitlines()
    assert len(decisions) == 1
    latest = json.loads(decisions[0])
    assert latest["decision"] == "validate_best_candidate"
    assert latest["workflow_loop"] == "pass_alpha_improvement_loop"
    assert paths.passed_alphas.exists()
    assert "C_pass" in paths.best_alphas.read_text(encoding="utf-8")


def test_research_tracks_pass_alpha_search_loop_before_validation(tmp_path):
    research_dir = tmp_path / "research"
    initialize_research_dir(research_dir)
    paths = research_paths(research_dir)

    record_research_artifacts(
        research_dir,
        [
            {
                "recorded_at": "2026-05-09T00:00:00Z",
                "candidate_id": "A_search",
                "family": "long_horizon_return_zscore_reversal",
                "expression": "signed_power(-ts_decay_linear(returns, 20), 0.95)",
                "result_id": "alpha-0",
                "metrics": {
                    "sharpe": 0.94,
                    "fitness": 0.64,
                    "returns": 0.1659,
                    "drawdown": 0.1451,
                    "turnover": 0.3538,
                    "checks_failed": 2,
                },
            }
        ],
        [],
    )

    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    family = memory["families"]["long_horizon_return_zscore_reversal"]
    decision = json.loads(paths.experiment_decisions.read_text(encoding="utf-8").splitlines()[-1])

    assert family["workflow_loop"] == "pass_alpha_search_loop"
    assert decision["workflow_loop"] == "pass_alpha_search_loop"


def test_research_artifacts_record_platform_error(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    record_research_artifacts(
        research_dir,
        [],
        [
            {
                "recorded_at": "2026-05-09T00:00:00Z",
                "candidate_id": "A_bad",
                "family": "manual",
                "expression": "bad_operator(close)",
                "error_type": "RuntimeError",
                "error": "unsupported operator",
            }
        ],
    )

    failed = paths.failed_alphas.read_text(encoding="utf-8")
    assert "A_bad" in failed
    assert "operator_invalid" in failed


def test_research_replaces_mock_best_with_live_result(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "A_mock",
                "family": "f",
                "expression": "rank(close)",
                "result_id": "mock-1",
                "metrics": {"fitness": 1.5, "turnover": 0.2, "raw": {"mode": "mock"}},
            }
        ],
        [],
    )
    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "A_live",
                "family": "f",
                "expression": "rank(close)",
                "result_id": "alpha-1",
                "metrics": {"fitness": 0.64, "sharpe": 0.94, "turnover": 0.3538, "raw": {"is": {"checks": [{"name": "LOW_SHARPE", "result": "FAIL"}]}}},
            }
        ],
        [],
    )

    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    assert memory["global_best"]["candidate_id"] == "A_live"
    assert memory["families"]["f"]["best_candidate"]["candidate_id"] == "A_live"

    latest_decision = json.loads(paths.experiment_decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert latest_decision["decision"] == "fix_validation_failure"
    assert latest_decision["dominant_bottleneck"] == "validation_failed"


def test_research_records_one_change_lessons_in_family_memory(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "A1",
                "family": "f",
                "expression": "rank(close)",
                "result_id": "alpha-1",
                "metrics": {"fitness": 0.6, "sharpe": 0.9, "turnover": 0.35, "drawdown": 0.14, "raw": {"is": {"checks": []}}},
            }
        ],
        [],
    )
    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "A2",
                "family": "f",
                "expression": "ts_decay_linear(rank(close), 60)",
                "result_id": "alpha-2",
                "metadata": {"parent_candidate_id": "A1", "changed_dimension": "decay_20_to_60"},
                "metrics": {"fitness": 0.96, "sharpe": 1.04, "turnover": 0.2, "drawdown": 0.16, "raw": {"is": {"checks": []}}},
            }
        ],
        [],
    )

    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    lessons = memory["families"]["f"]["lessons"]
    assert lessons
    assert lessons[-1]["changed_dimension"] == "decay_20_to_60"
    assert "fitness 0.6->0.96" in lessons[-1]["summary"]
    assert memory["lessons"][-1]["candidate_id"] == "A2"
