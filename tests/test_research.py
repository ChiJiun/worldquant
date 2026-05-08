import json

from app.research import initialize_research_dir, record_research_artifacts


def test_research_artifacts_record_validation_candidate(tmp_path):
    research_dir = tmp_path / "research"
    initialize_research_dir(research_dir)

    record_research_artifacts(
        research_dir,
        [
            {
                "recorded_at": "2026-05-09T00:00:00Z",
                "candidate_id": "A_best",
                "family": "long_horizon_return_zscore_reversal",
                "expression": "signed_power(-ts_decay_linear(returns, 90), 0.95)",
                "result_id": "alpha-1",
                "metrics": {
                    "sharpe": 1.18,
                    "fitness": 1.39,
                    "returns": 0.1724,
                    "drawdown": 0.1201,
                    "turnover": 0.1074,
                    "checks_failed": 0,
                },
            }
        ],
        [],
    )

    memory = json.loads((research_dir / "family_memory.json").read_text(encoding="utf-8"))
    family = memory["families"]["long_horizon_return_zscore_reversal"]
    assert family["status"] == "candidate_validation"
    assert family["best_candidate"]["candidate_id"] == "A_best"
    assert memory["global_best"]["candidate_id"] == "A_best"

    decisions = (research_dir / "experiment_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(decisions) == 1
    assert json.loads(decisions[0])["decision"] == "validate_best_candidate"
    assert (research_dir / "passed_alphas.csv").exists()
    assert "A_best" in (research_dir / "best_alphas.txt").read_text(encoding="utf-8")


def test_research_artifacts_record_platform_error(tmp_path):
    research_dir = tmp_path / "research"
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

    failed = (research_dir / "failed_alphas.csv").read_text(encoding="utf-8")
    assert "A_bad" in failed
    assert "operator_invalid" in failed


def test_research_artifacts_record_platform_passed_candidate(tmp_path):
    research_dir = tmp_path / "research"
    initialize_research_dir(research_dir)

    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "C_submit",
                "family": "ensemble",
                "expression": "zscore(rank(close)) + zscore(rank(volume))",
                "result_id": "alpha-2",
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

    decisions = (research_dir / "experiment_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    latest = json.loads(decisions[-1])
    assert latest["decision"] == "validate_best_candidate"
    assert latest["dominant_bottleneck"] == "validation_pending"
    assert "C_submit" in (research_dir / "passed_alphas.csv").read_text(encoding="utf-8")
    assert not (research_dir / "failed_alphas.csv").exists()


def test_research_replaces_mock_best_with_live_result(tmp_path):
    research_dir = tmp_path / "research"
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

    memory = json.loads((research_dir / "family_memory.json").read_text(encoding="utf-8"))
    assert memory["global_best"]["candidate_id"] == "A_live"
    assert memory["families"]["f"]["best_candidate"]["candidate_id"] == "A_live"

    latest_decision = json.loads((research_dir / "experiment_decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert latest_decision["decision"] == "fix_validation_failure"
    assert latest_decision["dominant_bottleneck"] == "validation_failed"


def test_research_records_one_change_lessons_in_family_memory(tmp_path):
    research_dir = tmp_path / "research"
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

    memory = json.loads((research_dir / "family_memory.json").read_text(encoding="utf-8"))
    lessons = memory["families"]["f"]["lessons"]
    assert lessons
    assert lessons[-1]["changed_dimension"] == "decay_20_to_60"
    assert "fitness 0.6->0.96" in lessons[-1]["summary"]
    assert memory["lessons"][-1]["candidate_id"] == "A2"
