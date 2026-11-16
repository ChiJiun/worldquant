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
    assert report["vs_parent"]["reference_found_in"] == str(passed)
    assert "reference_source" not in report["vs_parent"]
    assert report["vs_parent"]["deltas"]["fitness"]["from"] == 2.6
    assert report["vs_parent"]["improved"] == ["fitness", "turnover"]
    assert report["vs_parent"]["worsened"] == ["sharpe"]
    assert set(report["vs_parent"]["missing"]) == {"returns", "margin", "drawdown"}


def test_compare_metrics_is_incomparable_when_the_parent_has_no_metrics():
    comparison = compare_metrics({"metrics": {"fitness": 1.5}}, {"metrics": {}})

    assert comparison["verdict"] == "incomparable"
    assert comparison["deltas"] == {}
    assert comparison["unchanged"] == []

    memory = {"families": {}, "global_best": None}
    parent = _snapshot("P_ERR")  # error row: no metrics at all
    child = _snapshot("C1", metadata={"parent_candidate_id": "P_ERR", "changed_dimension": "decay"}, fitness=1.1)
    memory = {"families": {"f": {"best_candidate": child, "recent_candidates": [parent, child]}}, "global_best": child}

    report = build_attribution(memory, "C1")

    assert report["verdict"] == "incomparable"
    assert "no comparable metrics" in report["next_action_hint"]
    assert "drop it" not in report["next_action_hint"]


def test_find_in_alpha_csv_skips_error_rows_without_metrics(tmp_path):
    from app.attribution import find_in_alpha_csv

    failed = tmp_path / "failed_alphas.csv"
    failed.write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision,dominant_bottleneck,error_type,error",
                "2026-05-22T02:31:02Z,P1,f,rank(close),alpha-p,0.9,0.8,0.05,0.1,0.3,record_failure,sharpe_too_low,,",
                "2026-05-23T02:31:02Z,P1,f,rank(close),,,,,,,record_failure,platform_timeout,TimeoutError,timed out",
                "2026-05-24T02:31:02Z,P2,f,rank(open),,,,,,,record_failure,platform_error,RuntimeError,boom",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    found = find_in_alpha_csv(failed, "P1")

    assert found["result_id"] == "alpha-p"
    assert found["metrics"]["fitness"] == 0.8
    assert found["found_in"] == str(failed)
    assert "source" not in found
    assert find_in_alpha_csv(failed, "P2") is None
    assert find_in_alpha_csv(failed, "P1", result_id="alpha-x") is None


def test_find_in_alpha_csv_and_decisions_match_on_result_id_alone_and_do_not_copy_source(tmp_path):
    from app.attribution import find_in_alpha_csv, find_in_decisions

    passed = tmp_path / "passed_alphas.csv"
    passed.write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision,source",
                "2026-05-22T02:31:02Z,A1,f,rank(close),alpha-a,0.9,0.8,0.05,0.1,0.3,validate_best_candidate,live",
                "2026-05-23T02:31:02Z,B1,g,rank(open),alpha-b,1.9,1.8,0.05,0.1,0.3,validate_best_candidate,mock",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    decisions = tmp_path / "experiment_decisions.jsonl"
    decisions.write_text(
        json.dumps({"candidate_id": "B1", "family": "g", "result_id": "alpha-b", "metrics": {"fitness": 1.8}, "source": "mock"}) + "\n",
        encoding="utf-8",
    )

    found = find_in_alpha_csv(passed, None, result_id="alpha-b")
    assert found["candidate_id"] == "B1"
    assert found["found_in"] == str(passed)
    assert "source" not in found
    assert find_in_alpha_csv(passed, None) is None
    assert find_in_alpha_csv(passed, None, result_id="alpha-404") is None

    row = find_in_decisions(decisions, None, result_id="alpha-b")
    assert row["candidate_id"] == "B1"
    assert row["found_in"] == str(decisions)
    assert row["source"] == "mock"
    assert find_in_decisions(decisions, None) is None
    assert find_in_decisions(decisions, "A1", result_id="alpha-b") is None


def test_build_attribution_result_id_picks_the_reused_candidate_and_warns_otherwise():
    first = _snapshot("DUP", family="a", fitness=1.0, sharpe=1.0)
    first["result_id"] = "alpha-a"
    second = _snapshot("DUP", family="b", fitness=2.0, sharpe=2.0)
    second["result_id"] = "alpha-b"
    memory = {
        "families": {
            "a": {"best_candidate": first, "recent_candidates": [first]},
            "b": {"best_candidate": second, "recent_candidates": [second]},
        },
        "global_best": second,
    }

    report = build_attribution(memory, "DUP")
    assert report["result_id"] == "alpha-a"
    assert "appears in families ['a', 'b']" in report["warning"]
    assert "alpha-a" in report["warning"]

    report = build_attribution(memory, "DUP", result_id="alpha-b")
    assert report["result_id"] == "alpha-b"
    assert report["family"] == "b"
    assert "warning" not in report

    report = build_attribution(memory, result_id="alpha-b")
    assert report["candidate_id"] == "DUP"
    assert report["vs_global_best"] == {"status": "is_global_best"}

    with pytest.raises(ValueError, match=r"DUP \(result_id=alpha-404\)"):
        build_attribution(memory, "DUP", result_id="alpha-404")
    report = build_attribution(memory, result_id="alpha-a")
    assert report["result_id"] == "alpha-a"
    assert report["family"] == "a"
    assert "warning" not in report
    assert find_candidate(memory, "DUP", result_id="alpha-b") is second


def test_compare_or_self_tells_a_reused_candidate_id_apart_by_result_id():
    first = _snapshot("DUP", family="a", fitness=1.0, sharpe=1.0)
    first["result_id"] = "alpha-a"
    second = _snapshot("DUP", family="b", fitness=2.0, sharpe=2.0)
    second["result_id"] = "alpha-b"
    memory = {
        "families": {
            "a": {"best_candidate": first, "recent_candidates": [first]},
            "b": {"best_candidate": second, "recent_candidates": [second]},
        },
        "global_best": second,
    }

    report = build_attribution(memory, "DUP", result_id="alpha-a")
    assert report["vs_family_best"] == {"status": "is_family_best"}
    assert report["vs_global_best"]["reference_candidate_id"] == "DUP"
    assert report["vs_global_best"]["reference_result_id"] == "alpha-b"
    assert report["vs_global_best"]["deltas"]["fitness"]["from"] == 2.0
    assert report["vs_global_best"]["deltas"]["fitness"]["to"] == 1.0

    report = build_attribution(memory, result_id="alpha-b")
    assert report["vs_global_best"] == {"status": "is_global_best"}

    # Without result ids on both sides the candidate id decides, as before.
    third = _snapshot("C", family="c", fitness=1.0)
    third["result_id"] = ""
    best = dict(third, metrics={"fitness": 3.0})
    del best["result_id"]
    memory = {"families": {"c": {"best_candidate": best, "recent_candidates": [third]}}, "global_best": best}
    report = build_attribution(memory, "C")
    assert report["vs_global_best"] == {"status": "is_global_best"}

    other = _snapshot("D", family="c", fitness=1.0)
    del other["result_id"]
    memory["families"]["c"]["recent_candidates"].append(other)
    report = build_attribution(memory, "D")
    assert report["vs_global_best"]["reference_candidate_id"] == "C"
    assert "reference_result_id" not in report["vs_global_best"]


def test_build_attribution_result_id_alone_searches_every_family_not_only_the_global_best(tmp_path):
    first = _snapshot("A1", family="a", fitness=1.0, sharpe=1.0)
    second = _snapshot("B1", family="b", fitness=2.0, sharpe=2.0)
    memory = {
        "families": {
            "a": {"best_candidate": first, "recent_candidates": [first]},
            "b": {"best_candidate": second, "recent_candidates": [second]},
        },
        "global_best": second,
    }

    report = build_attribution(memory, result_id="alpha-A1")
    assert report["candidate_id"] == "A1"
    assert report["family"] == "a"
    assert report["vs_global_best"]["reference_candidate_id"] == "B1"
    assert "warning" not in report

    with pytest.raises(ValueError, match=r"<any candidate> \(result_id=alpha-404\)"):
        build_attribution(memory, result_id="alpha-404")

    passed = tmp_path / "passed_alphas.csv"
    passed.write_text(
        "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision,source\n"
        "2026-05-22T02:31:02Z,M1,m,rank(close),alpha-manual,0.9,0.8,0.05,0.1,0.3,validate_best_candidate,live\n",
        encoding="utf-8",
    )
    report = build_attribution(memory, result_id="alpha-manual", csv_paths=(passed,))
    assert report["candidate_id"] == "M1"
    assert report["family"] == "m"
    assert report["vs_global_best"]["reference_candidate_id"] == "B1"
