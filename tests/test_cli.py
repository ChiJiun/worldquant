from pathlib import Path

import csv
import json

import pytest

from app.cli import _init_data, main, merge_fetched_metrics


def test_init_data_copies_candidate_example(settings):
    assert not settings.candidate_file.exists()

    _init_data(settings)

    example = (Path(__file__).resolve().parents[1] / "data" / "candidates.example.jsonl").read_text(encoding="utf-8")
    assert settings.candidate_file.read_text(encoding="utf-8") == example


def test_research_mode_reports_requested_loop(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    settings.research_dir.mkdir(parents=True, exist_ok=True)
    (settings.research_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {
                    "f": {
                        "status": "development",
                        "best_candidate": {
                            "candidate_id": "C_pass",
                            "decision": "validate_best_candidate",
                            "metrics": {"fitness": 1.1},
                        },
                        "recent_candidates": [],
                    }
                },
                "global_best": {"candidate_id": "C_pass", "family": "f"},
                "lessons": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    exit_code = main(["research", "--mode", "pass-alpha-improvement"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_mode"] == "pass-alpha-improvement"
    assert payload["active_mode"] == "pass_alpha_improvement_loop"
    assert payload["suggested_next_action"]["type"] in {"test_formula", "validate_checks"}


def test_simulate_accepts_per_run_setting_overrides(settings, monkeypatch):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )

    exit_code = main([
        "simulate",
        "--allow-mock",
        "--limit",
        "1",
        "--current-run",
        "--universe",
        "TOP1000",
        "--delay",
        "0",
        "--decay",
        "3",
        "--truncation",
        "0.05",
        "--neutralization",
        "MARKET",
        "--lookback",
        "252",
        "--max-trade",
        "ON",
        "--max-position",
        "OFF",
    ])

    assert exit_code == 0
    summary = json.loads((settings.output_dir / "current_run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["settings"]["universe"] == "TOP1000"
    assert summary["settings"]["delay"] == 0
    assert summary["settings"]["decay"] == 3
    assert summary["settings"]["truncation"] == 0.05
    assert summary["settings"]["neutralization"] == "MARKET"
    assert summary["settings"]["lookback"] == 252
    assert summary["settings"]["maxTrade"] == "ON"
    assert summary["settings"]["maxPosition"] == "OFF"


def test_record_passed_alpha_cli_appends_row(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    exit_code = main([
        "record-passed-alpha",
        "--candidate-id",
        "BLUE_001",
        "--family",
        "blue_ocean",
        "--expression",
        "rank(close)",
        "--result-id",
        "alpha-1",
        "--sharpe",
        "1.5",
        "--fitness",
        "1.2",
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result_id"] == "alpha-1"
    assert payload["returns"] == ""
    text = (Path("research") / "logs" / "passed_alphas.csv").read_text(encoding="utf-8")
    assert text.count("\n") == 2
    assert "BLUE_001,blue_ocean,rank(close),alpha-1,1.5,1.2,,,,validate_best_candidate" in text


def test_merge_fetched_metrics_keeps_explicit_values():
    row = {"sharpe": 2.0, "fitness": None, "returns": None, "drawdown": None, "turnover": None}
    fetched = {"sharpe": 1.0, "fitness": 1.3, "returns": 0.1, "drawdown": 0.04, "turnover": 0.3, "alpha_id": "x"}

    merged = merge_fetched_metrics(row, fetched)

    assert merged["sharpe"] == 2.0
    assert merged["fitness"] == 1.3
    assert merged["turnover"] == 0.3
    assert "alpha_id" not in merged


def test_record_passed_alpha_cli_refuses_fetch_metrics_in_dry_run(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    with pytest.raises(SystemExit) as exc_info:
        main([
            "record-passed-alpha",
            "--candidate-id",
            "C1",
            "--family",
            "f",
            "--expression",
            "rank(close)",
            "--result-id",
            "alpha-1",
            "--fetch-metrics",
        ])

    assert exc_info.value.code == 2
    assert "needs a live BRAIN client" in capsys.readouterr().err
    assert not (Path("research") / "logs" / "passed_alphas.csv").exists()


def test_fetch_correlations_cli_caches_passed_alphas_with_mock_client(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    logs_dir = Path("research") / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "passed_alphas.csv").write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,pv,"rank(close)",alpha-1,1.3,1.1,0.10,0.05,0.20,validate_best_candidate',
                '2026-05-10T00:00:00Z,A2,pv,"rank(open)",alpha-2,1.3,1.1,0.10,0.05,0.20,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["fetch-correlations", "--kind", "both", "--limit", "3", "--allow-mock"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_alpha_count"] == 2
    assert len(payload["fetched"]) == 3
    assert payload["stopped_at_limit"] is True
    assert payload["dry_run"] is True
    assert payload["mock_cache"] is True
    cache = json.loads((Path("research") / "state" / "alpha_correlations.json").read_text(encoding="utf-8"))
    assert set(cache["alphas"]) == {"alpha-1", "alpha-2"}
    # mock entries carry no value, so selection treats these alphas as not covered by the platform
    assert cache["alphas"]["alpha-1"]["self"]["max_correlation"] is None


def test_fetch_correlations_cli_refuses_mock_client_without_allow_mock(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    with pytest.raises(SystemExit) as exc_info:
        main(["fetch-correlations", "--alpha-id", "alpha-1"])

    assert exc_info.value.code == 2
    assert "needs a live BRAIN client" in capsys.readouterr().err
    assert not (Path("research") / "state" / "alpha_correlations.json").exists()


def test_fetch_correlations_cli_requires_alpha_ids(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    with pytest.raises(SystemExit) as exc_info:
        main(["fetch-correlations", "--allow-mock"])

    assert exc_info.value.code == 2
    assert "no alpha ids" in capsys.readouterr().err


def test_attribute_cli_prints_parent_comparison(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    state_dir = Path("research") / "state"
    state_dir.mkdir(parents=True)
    parent = {"candidate_id": "P1", "family": "f", "expression": "rank(close)", "result_id": "a-p", "metrics": {"fitness": 1.0, "sharpe": 1.2, "turnover": 0.3}}
    child = {
        "candidate_id": "C1",
        "family": "f",
        "expression": "rank(open)",
        "result_id": "a-c",
        "metrics": {"fitness": 1.4, "sharpe": 1.3, "turnover": 0.5},
        "metadata": {"parent_candidate_id": "P1", "changed_dimension": "field_close_to_open"},
    }
    (state_dir / "family_memory.json").write_text(
        json.dumps({"families": {"f": {"best_candidate": child, "recent_candidates": [parent, child]}}, "global_best": child}),
        encoding="utf-8",
    )

    exit_code = main(["attribute", "--candidate-id", "C1"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidate_id"] == "C1"
    assert payload["vs_parent"]["verdict"] == "improvement_with_trade_off"
    assert payload["vs_global_best"] == {"status": "is_global_best"}

    exit_code = main(["attribute"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["candidate_id"] == "C1"

    exit_code = main(["attribute", "--candidate-id", "NOPE"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert "NOPE" in captured.err


def test_validate_candidate_cli_reports_missing_memory_without_traceback(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    exit_code = main(["validate-candidate", "--candidate-id", "A1"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "family_memory.json is missing or empty" in captured.err


def test_validate_candidate_cli_refuses_refresh_in_dry_run(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    with pytest.raises(SystemExit) as exc_info:
        main(["validate-candidate", "--refresh"])

    assert exc_info.value.code == 2
    assert "needs a live BRAIN client" in capsys.readouterr().err


def test_simulate_cli_refuses_mock_client_without_allow_mock(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["simulate", "--limit", "1", "--current-run"])

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "needs a live BRAIN client" in err
    assert "--allow-mock" in err
    assert not (Path("research") / "logs").exists()
    assert not (Path("outputs") / "current_run").exists()


def test_simulate_cli_allow_mock_tags_rows_and_select_alphas_skips_them(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )

    exit_code = main(["simulate", "--allow-mock", "--limit", "1", "--current-run"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "source=mock" in captured.err
    logs_dir = Path("research") / "logs"
    passed_rows = list(csv.DictReader((logs_dir / "passed_alphas.csv").open(encoding="utf-8", newline="")))
    assert [row["candidate_id"] for row in passed_rows] == ["A1"]
    assert passed_rows[0]["source"] == "mock"
    decision = json.loads((logs_dir / "experiment_decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert decision["source"] == "mock"
    summary = json.loads((Path("outputs") / "current_run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["source"] == "mock"

    exit_code = main(["select-alphas"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["record_count"] == 0
    assert report["mock_rows_skipped"] == 1
    assert report["submit_queue_count"] == 0
    assert "mock_rows_skipped: 1" in (Path("outputs") / "correlation_report.md").read_text(encoding="utf-8")


def test_result_cli_turns_mock_key_error_into_error_exit(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    exit_code = main(["result", "no-such-alpha"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.startswith("error: KeyError: ")
    assert "no-such-alpha" in captured.err


def _write_memory_with_reused_candidate_id(research_dir):
    state_dir = research_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    first = {"candidate_id": "DUP", "family": "a", "expression": "rank(close)", "result_id": "alpha-a", "metrics": {"fitness": 1.0, "sharpe": 1.0}}
    second = {"candidate_id": "DUP", "family": "b", "expression": "rank(open)", "result_id": "alpha-b", "metrics": {"fitness": 2.0, "sharpe": 2.0}}
    (state_dir / "family_memory.json").write_text(
        json.dumps(
            {
                "families": {
                    "a": {"best_candidate": first, "recent_candidates": [first]},
                    "b": {"best_candidate": second, "recent_candidates": [second]},
                },
                "global_best": second,
            }
        ),
        encoding="utf-8",
    )


def test_attribute_cli_result_id_picks_reused_candidate_and_warns_without_it(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    _write_memory_with_reused_candidate_id(Path("research"))

    exit_code = main(["attribute", "--candidate-id", "DUP"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["result_id"] == "alpha-a"
    assert "appears in families ['a', 'b']" in payload["warning"]
    assert captured.err.startswith("warning: ")

    exit_code = main(["attribute", "--candidate-id", "DUP", "--result-id", "alpha-b"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["result_id"] == "alpha-b"
    assert payload["expression"] == "rank(open)"
    assert "warning" not in payload
    assert captured.err == ""

    exit_code = main(["attribute", "--candidate-id", "DUP", "--result-id", "alpha-404"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "result_id=alpha-404" in captured.err

    exit_code = main(["attribute", "--result-id", "alpha-a"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["result_id"] == "alpha-a"
    assert payload["family"] == "a"
    assert payload["expression"] == "rank(close)"
    assert "warning" not in payload
    assert captured.err == ""

    exit_code = main(["attribute", "--result-id", "alpha-404"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "<any candidate> (result_id=alpha-404)" in captured.err


def test_validate_candidate_cli_result_id_alone_is_not_ignored(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    _write_memory_with_reused_candidate_id(Path("research"))

    exit_code = main(["validate-candidate", "--result-id", "alpha-a"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result_id"] == "alpha-a"
    assert payload["candidate_id"] == "DUP"
    assert payload["expression"] == "rank(close)"

    exit_code = main(["validate-candidate", "--result-id", "alpha-404"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "result_id=alpha-404" in captured.err


def test_validate_and_attribute_cli_report_corrupt_family_memory(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    state_dir = Path("research") / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "family_memory.json").write_text("{not json", encoding="utf-8")

    assert main(["validate-candidate", "--candidate-id", "A1"]) == 1
    err = capsys.readouterr().err
    assert "corrupt" in err
    assert "missing or empty" not in err

    assert main(["attribute"]) == 1
    assert "corrupt" in capsys.readouterr().err

    assert main(["research"]) == 1
    assert "corrupt" in capsys.readouterr().err
    assert (state_dir / "family_memory.json").read_text(encoding="utf-8") == "{not json"


def test_fetch_correlations_cli_default_alpha_ids_fall_back_to_legacy_passed_alphas(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)
    legacy = Path("research") / "passed_alphas.csv"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        "\n".join(
            [
                "recorded_at,candidate_id,family,expression,result_id,sharpe,fitness,returns,drawdown,turnover,decision",
                '2026-05-10T00:00:00Z,A1,pv,"rank(close)",alpha-legacy,1.3,1.1,0.10,0.05,0.20,validate_best_candidate',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["fetch-correlations", "--allow-mock"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_alpha_count"] == 1
    assert payload["fetched"][0]["alpha_id"] == "alpha-legacy"
