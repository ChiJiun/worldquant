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
