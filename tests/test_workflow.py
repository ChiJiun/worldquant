import json

from app.models import AlphaCandidate, ExpressionNode, RewardBreakdown, SimulationMetrics
from app.storage import StorageRepository
from app.workflow import AlphaDiscoveryWorkflow


def test_workflow_runs_hypothesis_file_with_mock_client(settings):
    settings.sharpe_threshold = 0.0
    settings.fitness_threshold = 0.0
    settings.ensure_directories()
    hypotheses = settings.output_dir / "alpha_hypotheses.json"
    hypotheses.write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "id": "test_hypothesis",
                        "family": "test_family",
                        "rationale": "A testable economic mechanism.",
                        "alphas": [{"expression": "rank(close)"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = AlphaDiscoveryWorkflow(settings)
    try:
        report = runner.run(hypotheses, promote=True)
    finally:
        runner.close()

    assert report.exists()
    assert "test_family" in report.read_text(encoding="utf-8")
    assert (settings.output_dir / "promotable_families.json").exists()


def test_passed_alpha_csv_records_full_metrics(settings):
    settings.ensure_directories()
    storage = StorageRepository(settings.storage_path, settings.output_dir)
    candidate = AlphaCandidate(
        expression="rank(open)",
        tree=ExpressionNode(kind="raw", value="rank(open)"),
        template_type="test_family",
        params={},
    )
    metrics = SimulationMetrics(
        sharpe=1.8,
        fitness=1.4,
        returns=0.08,
        drawdown=0.03,
        turnover=0.2,
        margin=0.01,
        extras={
            "alpha_id": "abc123",
            "grade": "A",
            "status": "UNSUBMITTED",
            "region": "USA",
            "delay": 1,
            "neutralization": "INDUSTRY",
            "triage_decision": "submit_ready",
            "quality_tier": "high",
            "checks_failed": 0,
        },
    )
    reward = RewardBreakdown(value=1.23, fitness_component=0.91, sharpe_component=0.54, penalty_component=0.0)

    try:
        storage.append_best_alpha(candidate, metrics, reward)
    finally:
        storage.close()

    passed = settings.output_dir / "passed_alphas.csv"
    header = passed.read_text(encoding="utf-8").splitlines()[0].split(",")
    for column in ["alpha_id", "grade", "status", "region", "delay", "neutralization", "triage_decision", "quality_tier", "sharpe", "fitness", "turnover", "margin", "reward"]:
        assert column in header


def test_workflow_records_template_candidates(settings):
    settings.ensure_directories()
    hypotheses = settings.output_dir / "alpha_hypotheses.json"
    hypotheses.write_text(
        json.dumps(
            {
                "session_id": "test_session",
                "hypotheses": [
                    {
                        "id": "test_hypothesis",
                        "family": "test_family",
                        "rationale": "A testable economic mechanism.",
                        "alphas": [{"expression": "rank(close)"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = AlphaDiscoveryWorkflow(settings)
    try:
        runner.run(hypotheses, promote=True)
        templates = runner.storage.list_alpha_templates()
    finally:
        runner.close()

    assert templates
    assert templates[0]["family"] == "test_family"


def test_workflow_outputs_use_stable_cumulative_files(settings):
    settings.ensure_directories()
    hypotheses = settings.output_dir / "alpha_hypotheses.json"
    hypotheses.write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "id": "test_hypothesis",
                        "family": "test_family",
                        "rationale": "A testable economic mechanism.",
                        "alphas": [{"expression": "rank(close)"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = AlphaDiscoveryWorkflow(settings)
    try:
        first_report = runner.run(hypotheses, promote=True)
        second_report = runner.run(hypotheses, promote=True)
    finally:
        runner.close()

    assert first_report == second_report
    assert first_report.name == "alpha_workflow_report.md"
    report_text = first_report.read_text(encoding="utf-8")
    assert report_text.count("## Run ") == 2

    promotable = json.loads((settings.output_dir / "promotable_families.json").read_text(encoding="utf-8"))
    assert len(promotable) == 2
    assert all(row["family"] == "test_family" for row in promotable)


def test_workflow_accepts_candidate_batch_contract(settings):
    settings.ensure_directories()
    candidates = settings.output_dir / "candidate_batch.json"
    candidates.write_text(
        json.dumps(
            {
                "candidate_batch_id": "test_batch",
                "candidates": [
                    {
                        "candidate_id": "A_test_001",
                        "hypothesis_id": "H_test_001",
                        "family": "candidate_contract_family",
                        "expression": "rank(close)",
                        "changed_dimension": "base_version",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = AlphaDiscoveryWorkflow(settings)
    try:
        report = runner.run(candidates, promote=True)
        templates = runner.storage.list_alpha_templates()
    finally:
        runner.close()

    assert report.exists()
    assert "candidate_contract_family" in report.read_text(encoding="utf-8")
    assert templates[0]["hypothesis_id"] == "H_test_001"
