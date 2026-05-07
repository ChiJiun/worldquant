from app.models import SimulationMetrics
from app.scoring import ResultScorer


def test_quality_classifier_high_medium_low():
    scorer = ResultScorer()

    high = SimulationMetrics(
        sharpe=2.1,
        fitness=1.4,
        returns=0.08,
        turnover=0.25,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )
    medium = SimulationMetrics(
        sharpe=1.7,
        fitness=1.05,
        returns=0.04,
        turnover=0.55,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )
    low = SimulationMetrics(
        sharpe=1.3,
        fitness=1.05,
        returns=0.1,
        turnover=0.55,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )
    rejected = SimulationMetrics(
        sharpe=0.3,
        fitness=0.1,
        returns=0.01,
        turnover=0.9,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )

    assert scorer.classify_quality(high) == "high"
    assert scorer.classify_quality(medium) == "medium"
    assert scorer.classify_quality(low) == "low"
    assert scorer.classify_quality(rejected) == "not_submittable"
    assert scorer.triage_decision(high) == "submit_ready"
    assert scorer.triage_decision(rejected) == "reject"
