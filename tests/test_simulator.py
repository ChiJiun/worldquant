import json

from app.api import MockBrainClient, RateLimiter
from app.research_paths import research_paths
from app.simulator import SimulateRunner, read_candidates


def test_read_candidates_from_jsonl(settings):
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )
    candidates = read_candidates(settings.candidate_file)
    assert len(candidates) == 1
    assert candidates[0].expression == "rank(close)"


def test_simulate_runner_writes_run_artifacts(settings):
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )
    runner = SimulateRunner(settings, MockBrainClient(RateLimiter(0.0)))
    run_dir = runner.run(settings.candidate_file)

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["total"] == 1
    assert summary["succeeded"] == 1
    assert (run_dir / "results.jsonl").exists()
    assert (settings.output_dir / "simulate_results.jsonl").exists()
    paths = research_paths(settings.research_dir)
    assert paths.family_memory.exists()
    assert paths.experiment_decisions.exists()


def test_simulate_runner_can_overwrite_current_run(settings):
    settings.ensure_directories()
    settings.candidate_file.write_text(
        '{"candidate_id":"A1","family":"manual","expression":"rank(close)"}\n',
        encoding="utf-8",
    )
    runner = SimulateRunner(settings, MockBrainClient(RateLimiter(0.0)))
    run_dir = runner.run(settings.candidate_file, archive_run=False)
    marker = run_dir / "old.txt"
    marker.write_text("kept", encoding="utf-8")
    settings.candidate_file.write_text(
        '{"candidate_id":"A2","family":"manual","expression":"rank(open)"}\n',
        encoding="utf-8",
    )

    second_run_dir = runner.run(settings.candidate_file, archive_run=False)

    assert run_dir == settings.output_dir / "current_run"
    assert second_run_dir == run_dir
    assert (second_run_dir / "results.jsonl").read_text(encoding="utf-8").count("\n") == 1
    assert marker.exists()
