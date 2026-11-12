import csv
import json

import pytest

from app.research import PASSED_FIELDS, initialize_research_dir, record_passed_alpha, record_research_artifacts
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


def test_record_passed_alpha_appends_normalized_row(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)

    written = record_passed_alpha(
        research_dir,
        {
            "candidate_id": "BLUE_001",
            "family": "blue_ocean",
            "expression": "rank(close)",
            "result_id": "alpha-1",
            "sharpe": "1.5",
            "fitness": 1.2,
            "returns": 0.1,
            "drawdown": 0.05,
            "turnover": 0.2,
        },
    )

    assert written["decision"] == "validate_best_candidate"
    assert written["recorded_at"].endswith("Z")
    assert written["sharpe"] == 1.5
    lines = paths.passed_alphas.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(PASSED_FIELDS)
    assert len(lines) == 2
    assert lines[1] == f"{written['recorded_at']},BLUE_001,blue_ocean,rank(close),alpha-1,1.5,1.2,0.1,0.05,0.2,validate_best_candidate,live"


def test_record_passed_alpha_rejects_duplicate_result_id_unless_allowed(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    row = {"candidate_id": "C1", "family": "f", "expression": "rank(close)", "result_id": "alpha-1"}
    record_passed_alpha(research_dir, row)

    with pytest.raises(ValueError, match="already exists"):
        record_passed_alpha(research_dir, row)
    assert len(paths.passed_alphas.read_text(encoding="utf-8").splitlines()) == 2

    record_passed_alpha(research_dir, row, allow_duplicate=True)
    assert len(paths.passed_alphas.read_text(encoding="utf-8").splitlines()) == 3


def test_record_passed_alpha_validates_required_fields_and_decision(tmp_path):
    research_dir = tmp_path / "research"
    base = {"candidate_id": "C1", "expression": "rank(close)", "result_id": "alpha-1"}

    with pytest.raises(ValueError, match="expression is required"):
        record_passed_alpha(research_dir, {**base, "expression": "  "})
    with pytest.raises(ValueError, match="candidate_id is required"):
        record_passed_alpha(research_dir, {**base, "candidate_id": ""})
    with pytest.raises(ValueError, match="result_id is required"):
        record_passed_alpha(research_dir, {**base, "result_id": "   "})
    with pytest.raises(ValueError, match="decision must be one of"):
        record_passed_alpha(research_dir, {**base, "decision": "record_failure"})
    assert not research_paths(research_dir).passed_alphas.exists()


def test_record_passed_alpha_rejects_non_finite_metrics_and_bad_timestamp(tmp_path):
    research_dir = tmp_path / "research"
    base = {"candidate_id": "C1", "expression": "rank(close)", "result_id": "alpha-1"}

    with pytest.raises(ValueError, match="sharpe must be a finite number"):
        record_passed_alpha(research_dir, {**base, "sharpe": float("nan")})
    with pytest.raises(ValueError, match="fitness must be a finite number"):
        record_passed_alpha(research_dir, {**base, "fitness": "inf"})
    with pytest.raises(ValueError, match="turnover must be a number"):
        record_passed_alpha(research_dir, {**base, "turnover": "abc"})
    with pytest.raises(ValueError, match="recorded_at must be an ISO-8601 timestamp"):
        record_passed_alpha(research_dir, {**base, "recorded_at": "yesterday"})
    assert not research_paths(research_dir).passed_alphas.exists()

    written = record_passed_alpha(research_dir, {**base, "recorded_at": "2026-05-21T08:09:57Z"})
    assert written["recorded_at"] == "2026-05-21T08:09:57Z"


def test_research_decision_records_parent_attribution_from_nested_metadata(tmp_path):
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
                "metadata": {"metadata": {"parent_candidate_id": "A1", "changed_dimension": "decay_20_to_60"}},
                "metrics": {"fitness": 0.96, "sharpe": 1.04, "turnover": 0.4, "drawdown": 0.16, "raw": {"is": {"checks": []}}},
            }
        ],
        [],
    )

    latest = json.loads(paths.experiment_decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert latest["parent_candidate_id"] == "A1"
    assert latest["changed_dimension"] == "decay_20_to_60"
    assert latest["latest_vs_parent"]["improved"] == ["sharpe", "fitness"]
    assert latest["latest_vs_parent"]["worsened"] == ["turnover", "drawdown"]
    assert latest["latest_vs_parent"]["verdict"] == "improvement_with_trade_off"
    assert latest["latest_vs_parent"]["reference_candidate_id"] == "A1"

    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    snapshot = memory["families"]["f"]["recent_candidates"][-1]
    assert snapshot["metadata"] == {"parent_candidate_id": "A1", "changed_dimension": "decay_20_to_60"}
    assert memory["families"]["f"]["lessons"][-1]["changed_dimension"] == "decay_20_to_60"


def test_research_decision_marks_missing_parent(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "A2",
                "family": "f",
                "expression": "rank(close)",
                "result_id": "alpha-2",
                "metadata": {"parent_candidate_id": "GHOST", "changed_dimension": "x"},
                "metrics": {"fitness": 0.9},
            },
            {
                "candidate_id": "A3",
                "family": "f",
                "expression": "rank(open)",
                "result_id": "alpha-3",
                "metrics": {"fitness": 0.9},
            },
        ],
        [],
    )

    rows = [json.loads(line) for line in paths.experiment_decisions.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["latest_vs_parent"] == {"status": "parent_not_found"}
    assert rows[1]["latest_vs_parent"] == {"status": "no_parent_recorded"}


def test_update_candidate_metrics_touches_every_snapshot():
    from app.research import update_candidate_metrics

    snap = {"candidate_id": "A1", "result_id": "alpha-1", "metrics": {"fitness": 0.5}}
    memory = {
        "families": {
            "f": {"best_candidate": dict(snap), "recent_candidates": [dict(snap), {"candidate_id": "A2", "metrics": {}}]},
        },
        "global_best": dict(snap),
    }

    updated = update_candidate_metrics(memory, "A1", {"fitness": 1.5}, result_id="alpha-1")

    assert updated == 3
    assert memory["families"]["f"]["best_candidate"]["metrics"] == {"fitness": 1.5}
    assert memory["families"]["f"]["recent_candidates"][0]["refreshed_at"].endswith("Z")
    assert memory["families"]["f"]["recent_candidates"][1]["metrics"] == {}
    assert memory["global_best"]["metrics"] == {"fitness": 1.5}
    # every snapshot owns its metrics dict; mutating one must not leak into the others
    memory["global_best"]["metrics"]["fitness"] = 9.9
    assert memory["families"]["f"]["best_candidate"]["metrics"] == {"fitness": 1.5}


def test_update_candidate_metrics_skips_snapshots_with_a_different_result_id():
    """The same candidate_id has been reused across families for different alphas; only the fetched alpha may change."""
    from app.research import update_candidate_metrics

    reused = {"candidate_id": "OP_EFF_001", "result_id": "alpha-other", "metrics": {"fitness": 0.4, "alpha_id": "alpha-other"}}
    target = {"candidate_id": "OP_EFF_001", "result_id": "alpha-1", "metrics": {"fitness": 0.5, "alpha_id": "alpha-1"}}
    memory = {
        "families": {
            "a": {"best_candidate": dict(target), "recent_candidates": [dict(target)]},
            "b": {"best_candidate": dict(reused), "recent_candidates": [dict(reused)]},
        },
        "global_best": dict(reused),
    }

    updated = update_candidate_metrics(memory, "OP_EFF_001", {"fitness": 1.5, "alpha_id": "alpha-1"}, result_id="alpha-1")

    assert updated == 2
    assert memory["families"]["a"]["best_candidate"]["metrics"]["fitness"] == 1.5
    assert memory["families"]["b"]["best_candidate"]["metrics"] == {"fitness": 0.4, "alpha_id": "alpha-other"}
    assert memory["families"]["b"]["recent_candidates"][0]["metrics"]["alpha_id"] == "alpha-other"
    assert memory["global_best"]["metrics"]["fitness"] == 0.4
    assert "refreshed_at" not in memory["global_best"]


def test_recorder_attributes_parent_that_only_exists_in_passed_alphas_csv(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    paths.passed_alphas.parent.mkdir(parents=True, exist_ok=True)
    paths.passed_alphas.write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                "2026-05-22T02:31:02Z,P_MANUAL,f,rank(close),alpha-p,2.24,2.51,0.1567,0.0549,0.0486,validate_best_candidate",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    record_research_artifacts(
        research_dir,
        [
            {
                "candidate_id": "C1",
                "family": "f",
                "expression": "rank(open)",
                "result_id": "alpha-c",
                "metadata": {"parent_candidate_id": "P_MANUAL", "changed_dimension": "field_close_to_open"},
                "metrics": {"fitness": 2.7, "sharpe": 2.3, "turnover": 0.04, "returns": 0.16, "drawdown": 0.05},
            }
        ],
        [],
    )

    latest = json.loads(paths.experiment_decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert latest["latest_vs_parent"]["reference_candidate_id"] == "P_MANUAL"
    assert latest["latest_vs_parent"]["reference_source"] == str(paths.passed_alphas)
    assert latest["latest_vs_parent"]["verdict"] == "net_improvement"
    memory = json.loads(paths.family_memory.read_text(encoding="utf-8"))
    assert memory["families"]["f"]["lessons"][-1]["parent_candidate_id"] == "P_MANUAL"


def test_recorder_tags_source_and_upgrades_a_legacy_csv_header(tmp_path):
    from app.research import FAILED_FIELDS

    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    paths.passed_alphas.parent.mkdir(parents=True, exist_ok=True)
    legacy_header = ",".join(PASSED_FIELDS[:-1])
    assert "source" not in legacy_header
    paths.passed_alphas.write_text(
        legacy_header + "\n" + '2026-05-22T02:31:02Z,OLD,f,"rank(close)",alpha-old,2.24,2.51,0.1567,0.0549,0.0486,validate_best_candidate\n',
        encoding="utf-8",
    )
    live = {"candidate_id": "LIVE", "family": "f", "expression": "rank(open)", "result_id": "alpha-live", "metrics": {"fitness": 1.5, "sharpe": 1.4, "turnover": 0.2}}
    mock = {"candidate_id": "MOCK", "family": "f", "expression": "rank(high)", "result_id": "deadbeef0000", "metrics": {"fitness": 1.6, "sharpe": 1.5, "turnover": 0.2, "alpha_id": "mock-deadbeef0000", "raw": {"mode": "mock"}}}
    error = {"candidate_id": "ERR", "family": "f", "expression": "bad(close)", "error_type": "RuntimeError", "error": "boom"}

    record_research_artifacts(research_dir, [live], [])
    record_research_artifacts(research_dir, [mock], [error], source="mock")

    rows = list(csv.DictReader(paths.passed_alphas.open(encoding="utf-8", newline="")))
    assert list(rows[0].keys()) == PASSED_FIELDS
    assert [(row["candidate_id"], row["source"]) for row in rows] == [("OLD", ""), ("LIVE", "live"), ("MOCK", "mock")]
    assert rows[0]["expression"] == "rank(close)"
    assert rows[0]["fitness"] == "2.51"
    failed = list(csv.DictReader(paths.failed_alphas.open(encoding="utf-8", newline="")))
    assert list(failed[0].keys()) == FAILED_FIELDS
    assert [(row["candidate_id"], row["source"]) for row in failed] == [("ERR", "mock")]
    decisions = [json.loads(line) for line in paths.experiment_decisions.read_text(encoding="utf-8").splitlines()]
    assert [(row["candidate_id"], row["source"]) for row in decisions] == [("LIVE", "live"), ("MOCK", "mock"), ("ERR", "mock")]


def test_recorder_tags_mock_metrics_as_mock_even_when_source_says_live(tmp_path):
    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    mock = {"candidate_id": "M", "family": "f", "expression": "rank(close)", "result_id": "abc", "metrics": {"fitness": 1.5, "sharpe": 1.4, "alpha_id": "mock-abc"}}

    record_research_artifacts(research_dir, [mock], [], source="live")

    rows = list(csv.DictReader(paths.passed_alphas.open(encoding="utf-8", newline="")))
    assert rows[0]["source"] == "mock"
    with pytest.raises(ValueError, match="source must be one of"):
        record_research_artifacts(research_dir, [mock], [], source="staging")


def test_append_csv_keeps_an_unknown_header_as_is(tmp_path):
    from app.research import _append_csv

    path = tmp_path / "custom.csv"
    path.write_text("candidate_id,extra,decision\nA,1,x\n", encoding="utf-8")

    _append_csv(path, PASSED_FIELDS, [{"candidate_id": "B", "decision": "y", "source": "live"}])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "candidate_id,extra,decision"
    assert lines[1:] == ["A,1,x", "B,,y"]


def test_load_family_memory_reports_corrupt_file_instead_of_empty_memory(tmp_path):
    from app.research import load_family_memory, summarize_workflow_state

    research_dir = tmp_path / "research"
    paths = research_paths(research_dir)
    paths.family_memory.parent.mkdir(parents=True, exist_ok=True)
    paths.family_memory.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt") as exc_info:
        load_family_memory(research_dir)
    assert str(paths.family_memory) in str(exc_info.value)
    with pytest.raises(ValueError, match="corrupt"):
        summarize_workflow_state(research_dir)
    with pytest.raises(ValueError, match="corrupt"):
        record_research_artifacts(research_dir, [{"candidate_id": "A", "family": "f", "expression": "rank(close)", "result_id": "r", "metrics": {"fitness": 1.0}}], [])
    # the damaged file is left for the user to repair, not overwritten by an empty memory
    assert paths.family_memory.read_text(encoding="utf-8") == "{not json"

    paths.family_memory.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a JSON object"):
        load_family_memory(research_dir)


def test_is_mock_metrics_recognizes_alpha_id_prefix():
    from app.research import _is_mock_metrics

    assert _is_mock_metrics({"raw": {"mode": "mock"}})
    assert _is_mock_metrics({"alpha_id": "mock-abc", "raw": {}})
    assert not _is_mock_metrics({"alpha_id": "O0ovlO0R", "raw": {"is": {}}})
    assert not _is_mock_metrics({})
