import json

import pytest

from app.attribution import build_attribution, candidate_metadata, compare_metrics, find_candidate


def _snapshot(candidate_id, family="f", metadata=None, **metrics):
    return {
        "candidate_id": candidate_id,
        "family": family,
        "expression": f"expr_{candidate_id}",
        "result_id": f"alpha-{candidate_id}",
        "metrics": metrics,
        "metadata": metadata or {},
    }


def test_candidate_metadata_flattens_nested_metadata_with_outer_keys_winning():
    result = {"metadata": {"notes": "outer", "metadata": {"parent_candidate_id": "P1", "changed_dimension": "decay", "notes": "inner"}}}

    flat = candidate_metadata(result)

    assert flat == {"parent_candidate_id": "P1", "changed_dimension": "decay", "notes": "outer"}
    assert candidate_metadata({"metadata": "not a dict"}) == {}
    assert candidate_metadata(None) == {}


@pytest.mark.parametrize(
    "child, parent, expected",
    [
        ({"fitness": 1.2, "sharpe": 1.5, "turnover": 0.2}, {"fitness": 1.0, "sharpe": 1.4, "turnover": 0.3}, "net_improvement"),
        ({"fitness": 0.8, "sharpe": 1.2, "turnover": 0.4}, {"fitness": 1.0, "sharpe": 1.4, "turnover": 0.3}, "regression"),
        ({"fitness": 1.2, "sharpe": 1.5, "turnover": 0.5}, {"fitness": 1.0, "sharpe": 1.4, "turnover": 0.3}, "improvement_with_trade_off"),
        ({"fitness": 0.9, "sharpe": 1.3, "turnover": 0.1}, {"fitness": 1.0, "sharpe": 1.4, "turnover": 0.3}, "regression_with_trade_off"),
        ({"returns": 0.2, "drawdown": 0.3}, {"returns": 0.1, "drawdown": 0.1}, "trade_off"),
        ({"fitness": 1.0}, {"fitness": 1.0}, "unchanged"),
    ],
)
def test_compare_metrics_verdicts(child, parent, expected):
    comparison = compare_metrics({"metrics": child}, {"metrics": parent})

    assert comparison["verdict"] == expected


def test_compare_metrics_reports_deltas_and_missing():
    comparison = compare_metrics({"metrics": {"fitness": 1.5, "turnover": 0.25}}, {"metrics": {"fitness": 1.0, "turnover": 0.5, "sharpe": 1.1}})

    assert comparison["deltas"]["fitness"] == {"from": 1.0, "to": 1.5, "delta": 0.5, "pct": 0.5}
    assert comparison["deltas"]["turnover"]["delta"] == -0.25
    assert comparison["improved"] == ["fitness", "turnover"]
    assert set(comparison["missing"]) == {"sharpe", "returns", "margin", "drawdown"}


def test_build_attribution_compares_parent_family_best_and_global_best():
    parent = _snapshot("P1", fitness=1.0, sharpe=1.2, turnover=0.30)
    child = _snapshot("C1", metadata={"parent_candidate_id": "P1", "changed_dimension": "decay_10_to_20"}, fitness=1.3, sharpe=1.4, turnover=0.25)
    other_best = _snapshot("G1", family="g", fitness=2.0, sharpe=2.0, turnover=0.2)
    memory = {
        "families": {
            "f": {"best_candidate": child, "recent_candidates": [parent, child]},
            "g": {"best_candidate": other_best, "recent_candidates": [other_best]},
        },
        "global_best": other_best,
    }

    report = build_attribution(memory, "C1")

    assert report["parent_candidate_id"] == "P1"
    assert report["changed_dimension"] == "decay_10_to_20"
    assert report["vs_parent"]["verdict"] == "net_improvement"
    assert report["vs_parent"]["reference_candidate_id"] == "P1"
    assert report["vs_family_best"] == {"status": "is_family_best"}
    assert report["vs_global_best"]["verdict"] == "regression"
    assert report["vs_global_best"]["reference_candidate_id"] == "G1"
    assert report["verdict"] == "net_improvement"
    assert "Keep decay_10_to_20" in report["next_action_hint"]


def test_build_attribution_defaults_to_global_best_and_reports_missing_parent():
    best = _snapshot("B1", metadata={"parent_candidate_id": "GHOST", "changed_dimension": "x"}, fitness=1.1)
    memory = {"families": {"f": {"best_candidate": best, "recent_candidates": [best]}}, "global_best": best}

    report = build_attribution(memory)

    assert report["candidate_id"] == "B1"
    assert report["vs_parent"] == {"status": "parent_not_found"}
    assert report["verdict"] == "parent_not_found"
    assert report["vs_global_best"] == {"status": "is_global_best"}

    no_parent = _snapshot("N1", fitness=1.0)
    report = build_attribution({"families": {}, "global_best": no_parent})
    assert report["verdict"] == "no_parent_recorded"
    assert "parent_candidate_id" in report["next_action_hint"]


def test_build_attribution_falls_back_to_decisions_log(tmp_path):
    decisions = tmp_path / "experiment_decisions.jsonl"
    decisions.write_text(
        "\n".join(
            [
                json.dumps({"candidate_id": "P1", "family": "f", "metrics": {"fitness": 0.9, "sharpe": 1.0}}),
                json.dumps({"candidate_id": "C1", "family": "f", "metrics": {"fitness": 1.2}, "metadata": {"metadata": {"parent_candidate_id": "P1", "changed_dimension": "power"}}}),
                "not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    legacy_child = {"candidate_id": "C1", "family": "f", "expression": "e", "result_id": "r", "metrics": {"fitness": 1.2, "sharpe": 1.1}}
    memory = {"families": {"f": {"best_candidate": legacy_child, "recent_candidates": [legacy_child]}}, "global_best": legacy_child}

    report = build_attribution(memory, "C1", decisions_path=decisions)

    assert report["parent_candidate_id"] == "P1"
    assert report["changed_dimension"] == "power"
    assert report["vs_parent"]["improved"] == ["sharpe", "fitness"]
    assert find_candidate(memory, "missing", decisions) is None


def test_build_attribution_raises_for_unknown_candidate():
    with pytest.raises(ValueError, match="Candidate not found"):
        build_attribution({"families": {}, "global_best": None}, "nope")
    with pytest.raises(ValueError, match="<global_best>"):
        build_attribution({"families": {}, "global_best": None})


def test_build_attribution_falls_back_to_passed_alphas_csv_for_manual_parent(tmp_path):
    passed = tmp_path / "passed_alphas.csv"
    passed.write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                "2026-05-22T02:31:02Z,P_MANUAL,f,rank(close),alpha-p,2.24,2.51,0.1567,0.0549,0.0486,validate_best_candidate",
                "2026-05-23T02:31:02Z,P_MANUAL,f,rank(close),alpha-p2,2.30,2.60,0.16,0.05,0.05,validate_best_candidate",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    child = _snapshot("C1", metadata={"parent_candidate_id": "P_MANUAL", "changed_dimension": "decay_45_to_55"}, fitness=2.7, sharpe=2.2, turnover=0.04)
    memory = {"families": {"f": {"best_candidate": child, "recent_candidates": [child]}}, "global_best": child}

    report = build_attribution(memory, "C1", csv_paths=(tmp_path / "missing.csv", passed))

    assert report["vs_parent"]["reference_candidate_id"] == "P_MANUAL"
    assert report["vs_parent"]["reference_source"] == str(passed)
    assert report["vs_parent"]["deltas"]["fitness"]["from"] == 2.6
    assert report["vs_parent"]["improved"] == ["fitness", "turnover"]
    assert report["vs_parent"]["worsened"] == ["sharpe"]
    assert set(report["vs_parent"]["missing"]) == {"returns", "margin", "drawdown"}
