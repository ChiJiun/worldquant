from app.models import SimulationMetrics
from app.scoring import ResultScorer


def test_quality_classifier_high_medium_low():
    scorer = ResultScorer()

    high = SimulationMetrics(
        sharpe=1.9,
        fitness=1.4,
        returns=0.08,
        turnover=0.25,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )
    medium = SimulationMetrics(
        sharpe=1.3,
        fitness=1.05,
        returns=0.04,
        turnover=0.55,
        extras={"checks_failed": 0, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )
    low = SimulationMetrics(
        sharpe=2.0,
        fitness=1.5,
        returns=0.1,
        turnover=0.2,
        extras={"checks_failed": 1, "behavior_similarity": 0.2, "region": "USA", "delay": 1},
    )

    assert scorer.classify_quality(high) == "high"
    assert scorer.classify_quality(medium) == "medium"
    assert scorer.classify_quality(low) == "low"
