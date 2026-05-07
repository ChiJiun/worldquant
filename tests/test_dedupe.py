from app.dedupe import DedupeService
from app.models import AlphaCandidate, ExpressionNode, SimulationMetrics


def test_dedupe_skips_exact_match(template_engine):
    candidate = template_engine.instantiate("momentum")
    service = DedupeService([(candidate.fingerprint, candidate.normalized_expression, candidate.template_type)])
    decision = service.should_skip(candidate)
    assert decision.should_skip is True
    assert decision.reason == "exact-fingerprint-match"


def test_dedupe_skips_structural_overlap(template_engine):
    first = template_engine.instantiate("mean_reversion", {"field_1": "close", "window_1": 10, "group": "sector", "wrappers": ["rank"]})
    second = template_engine.instantiate("mean_reversion", {"field_1": "close", "window_1": 20, "group": "sector", "wrappers": ["rank"]})
    service = DedupeService([(first.fingerprint, first.normalized_expression, first.template_type)], near_duplicate_threshold=0.6)
    decision = service.should_skip(second)
    assert decision.should_skip is True
    assert decision.reason == "high-structural-overlap"


def test_dedupe_flags_behavior_overlap():
    first_tree = ExpressionNode(kind="operator", value="rank", children=[ExpressionNode(kind="field", value="close")])
    second_tree = ExpressionNode(kind="operator", value="rank", children=[ExpressionNode(kind="field", value="vwap")])
    first = AlphaCandidate(expression=first_tree.to_expression(), tree=first_tree, template_type="momentum", params={}, wrappers=["rank"])
    second = AlphaCandidate(expression=second_tree.to_expression(), tree=second_tree, template_type="momentum", params={}, wrappers=["rank"])
    service = DedupeService()
    service.register(first)
    service.register_behavior(
        first,
        SimulationMetrics(
            sharpe=1.3,
            fitness=1.1,
            returns=0.08,
            drawdown=0.04,
            turnover=0.2,
            margin=0.05,
            extras={"checks": [], "stage_metrics": {"is": {"sharpe": 1.3, "fitness": 1.1, "returns": 0.08, "drawdown": 0.04}}},
        ),
    )
    decision = service.behavior_similarity(
        second,
        SimulationMetrics(
            sharpe=1.28,
            fitness=1.08,
            returns=0.079,
            drawdown=0.041,
            turnover=0.19,
            margin=0.051,
            extras={"checks": [], "stage_metrics": {"is": {"sharpe": 1.28, "fitness": 1.08, "returns": 0.079, "drawdown": 0.041}}},
        ),
    )
    assert decision.similarity > 0.9
