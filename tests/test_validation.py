import json

from app.validation import validate_candidate_from_memory


def test_validate_candidate_blocks_without_live_checks(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {},
                "global_best": {
                    "candidate_id": "A1",
                    "family": "long_horizon_return_zscore_reversal",
                    "expression": "rank(close)",
                    "result_id": "alpha-1",
                    "metrics": {"fitness": 1.3, "turnover": 0.2, "raw": {"mode": "mock"}},
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_candidate_from_memory(research_dir, persist=True)

    assert report["decision"] == "validation_incomplete"
    assert report["overall_status"] == "blocked"
    assert "self_corr" in report["blocking_checks"]
    assert (research_dir / "validation_reports.jsonl").exists()
    assert (research_dir / "validation_reports.csv").exists()


def test_validate_candidate_passes_available_platform_checks(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    raw = {
        "checks": [
            {"name": "WEIGHT_CONCENTRATION", "result": "PASS"},
            {"name": "SUB_UNIVERSE_SHARPE", "result": "PASS"},
            {"name": "SELF_CORRELATION", "result": "PASS"},
            {"name": "OUT_OF_SAMPLE", "result": "PASS"},
        ]
    }
    (research_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {},
                "global_best": {
                    "candidate_id": "A1",
                    "family": "f",
                    "expression": "rank(close)",
                    "result_id": "alpha-1",
                    "metrics": {"fitness": 1.3, "turnover": 0.2, "raw": raw},
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_candidate_from_memory(research_dir)

    assert report["decision"] == "promote_template"
    assert report["overall_status"] == "pass"
    assert report["blocking_checks"] == []


def test_validate_candidate_blocks_pending_self_correlation(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    raw = {
        "is": {
            "checks": [
                {"name": "CONCENTRATED_WEIGHT", "result": "PASS"},
                {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS"},
                {"name": "SELF_CORRELATION", "result": "PENDING"},
            ]
        }
    }
    (research_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {},
                "global_best": {
                    "candidate_id": "A1",
                    "family": "f",
                    "expression": "rank(close)",
                    "result_id": "alpha-1",
                    "metrics": {"fitness": 1.3, "turnover": 0.2, "raw": raw},
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_candidate_from_memory(research_dir)

    assert "self_corr" in report["blocking_checks"]
    assert report["checks"]["self_corr"]["status"] == "pending"


def test_validate_candidate_does_not_write_reports_by_default(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {},
                "global_best": {
                    "candidate_id": "A1",
                    "family": "f",
                    "expression": "rank(close)",
                    "result_id": "alpha-1",
                    "metrics": {"fitness": 1.3, "turnover": 0.2, "raw": {"mode": "mock"}},
                },
            }
        ),
        encoding="utf-8",
    )

    validate_candidate_from_memory(research_dir)

    assert not (research_dir / "validation_reports.jsonl").exists()
    assert not (research_dir / "validation_reports.csv").exists()
