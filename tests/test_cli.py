from pathlib import Path

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

    exit_code = main(["fetch-correlations", "--kind", "both", "--limit", "3"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_alpha_count"] == 2
    assert len(payload["fetched"]) == 3
    assert payload["stopped_at_limit"] is True
    assert payload["dry_run"] is True
    cache = json.loads((Path("research") / "state" / "alpha_correlations.json").read_text(encoding="utf-8"))
    assert set(cache["alphas"]) == {"alpha-1", "alpha-2"}
    assert cache["alphas"]["alpha-1"]["self"]["max_correlation"] == 0.0


def test_fetch_correlations_cli_requires_alpha_ids(settings, monkeypatch, capsys):
    monkeypatch.chdir(settings.candidate_file.parent.parent)

    with pytest.raises(SystemExit) as exc_info:
        main(["fetch-correlations"])

    assert exc_info.value.code == 2
    assert "no alpha ids" in capsys.readouterr().err
