from pathlib import Path

import json

from app.cli import _init_data, main


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
