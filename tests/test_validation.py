import json

from app.validation import validate_candidate_from_memory
from app.research_paths import research_paths


def test_validate_candidate_blocks_without_live_checks(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    paths = research_paths(research_dir)
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
    assert paths.validation_reports_jsonl.exists()
    assert paths.validation_reports_csv.exists()


def test_validate_candidate_passes_available_platform_checks(tmp_path):
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    paths = research_paths(research_dir)
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
    paths = research_paths(research_dir)
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

    assert not paths.validation_reports_jsonl.exists()
    assert not paths.validation_reports_csv.exists()


def _memory_with_pending_self_corr(research_dir, result_id="alpha-1"):
    raw = {
        "is": {
            "checks": [
                {"name": "CONCENTRATED_WEIGHT", "result": "PASS"},
                {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS"},
                {"name": "SELF_CORRELATION", "result": "PENDING"},
                {"name": "OUT_OF_SAMPLE", "result": "PASS"},
            ]
        }
    }
    candidate = {
        "candidate_id": "A1",
        "family": "f",
        "expression": "rank(close)",
        "result_id": result_id,
        "metrics": {"fitness": 1.3, "turnover": 0.2, "raw": raw},
    }
    (research_dir / "state").mkdir(parents=True, exist_ok=True)
    (research_dir / "state" / "family_memory.json").write_text(
        json.dumps({"families": {"f": {"best_candidate": candidate, "recent_candidates": [candidate]}}, "global_best": candidate}),
        encoding="utf-8",
    )
    return candidate


def _write_cache(research_dir, alpha_id, max_corr):
    (research_dir / "state").mkdir(parents=True, exist_ok=True)
    (research_dir / "state" / "alpha_correlations.json").write_text(
        json.dumps({"version": 1, "alphas": {alpha_id: {"self": {"max_correlation": max_corr, "records": []}}}}),
        encoding="utf-8",
    )


def test_validate_candidate_uses_cached_self_correlation_when_platform_pending(tmp_path):
    research_dir = tmp_path / "research"
    _memory_with_pending_self_corr(research_dir)
    _write_cache(research_dir, "alpha-1", 0.31)

    report = validate_candidate_from_memory(research_dir)

    assert report["checks"]["self_corr"]["status"] == "pass"
    assert report["checks"]["self_corr"]["source"] == "correlation_cache"
    assert "max=0.31" in report["checks"]["self_corr"]["reason"]
    assert report["blocking_checks"] == []
    assert report["decision"] == "promote_template"


def test_validate_candidate_fails_self_correlation_from_cache_at_threshold(tmp_path):
    research_dir = tmp_path / "research"
    _memory_with_pending_self_corr(research_dir)
    _write_cache(research_dir, "alpha-1", 0.7)

    report = validate_candidate_from_memory(research_dir)

    assert report["checks"]["self_corr"]["status"] == "fail"
    assert report["blocking_checks"] == ["self_corr"]
    assert report["next_action"]["type"] == "validate_checks"


def test_validate_candidate_refresh_updates_memory_and_correlation_cache(tmp_path):
    from app.api import MockBrainClient, RateLimiter
    from app.models import SimulationMetrics

    research_dir = tmp_path / "research"
    _memory_with_pending_self_corr(research_dir)
    client = MockBrainClient(RateLimiter(0.0))
    client.results["alpha-1"] = SimulationMetrics(
        alpha_id="alpha-1",
        status="IS",
        sharpe=1.9,
        fitness=1.6,
        turnover=0.21,
        checks_failed=0,
        raw={
            "is": {
                "checks": [
                    {"name": "CONCENTRATED_WEIGHT", "result": "PASS"},
                    {"name": "LOW_SUB_UNIVERSE_SHARPE", "result": "PASS"},
                    {"name": "SELF_CORRELATION", "result": "PASS", "value": 0.12},
                    {"name": "OUT_OF_SAMPLE", "result": "PASS"},
                ]
            }
        },
    )
    client.correlation_payloads[("alpha-1", "self")] = {"max": 0.12, "records": [{"id": "old-1", "correlation": 0.12}]}

    report = validate_candidate_from_memory(research_dir, refresh=True, client=client, persist=True)

    assert report["decision"] == "promote_template"
    assert report["checks"]["self_corr"]["status"] == "pass"
    assert report["refreshed"]["result_id"] == "alpha-1"
    assert report["refreshed"]["updated_snapshots"] == 3
    assert report["refreshed"]["self_correlation_max"] == 0.12
    assert report["metrics"]["fitness"] == 1.6

    memory = json.loads((research_dir / "state" / "family_memory.json").read_text(encoding="utf-8"))
    assert memory["global_best"]["metrics"]["fitness"] == 1.6
    assert memory["families"]["f"]["recent_candidates"][0]["refreshed_at"].endswith("Z")
    cache = json.loads((research_dir / "state" / "alpha_correlations.json").read_text(encoding="utf-8"))
    assert cache["alphas"]["alpha-1"]["self"]["max_correlation"] == 0.12
    assert research_paths(research_dir).validation_reports_jsonl.exists()


def test_validate_candidate_refresh_reports_correlation_error_but_keeps_metrics(tmp_path):
    from app.api import MockBrainClient, RateLimiter
    from app.models import SimulationMetrics

    class NoCorrelationClient(MockBrainClient):
        def fetch_self_correlation(self, alpha_id):
            raise RuntimeError("corr endpoint down")

    research_dir = tmp_path / "research"
    _memory_with_pending_self_corr(research_dir)
    client = NoCorrelationClient(RateLimiter(0.0))
    client.results["alpha-1"] = SimulationMetrics(alpha_id="alpha-1", fitness=1.1, raw={"is": {"checks": []}})

    report = validate_candidate_from_memory(research_dir, refresh=True, client=client)

    assert report["metrics"]["fitness"] == 1.1
    assert report["refreshed"]["self_correlation_error"].startswith("RuntimeError")
    assert not (research_dir / "state" / "alpha_correlations.json").exists()


def test_validate_candidate_refresh_requires_client_and_result_id(tmp_path):
    import pytest

    research_dir = tmp_path / "research"
    _memory_with_pending_self_corr(research_dir)
    with pytest.raises(ValueError, match="requires a BRAIN client"):
        validate_candidate_from_memory(research_dir, refresh=True)

    research_dir2 = tmp_path / "research2"
    _memory_with_pending_self_corr(research_dir2, result_id="")
    from app.api import MockBrainClient, RateLimiter

    with pytest.raises(ValueError, match="no result_id"):
        validate_candidate_from_memory(research_dir2, refresh=True, client=MockBrainClient(RateLimiter(0.0)))
