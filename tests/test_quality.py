from app.models import AlphaCandidate, ExpressionNode
from app.quality import CandidateQualityGate


def test_quality_gate_rejects_identity_subtraction():
    tree = ExpressionNode(
        kind="operator",
        value="rank",
        children=[
            ExpressionNode(
                kind="operator",
                value="sub",
                children=[
                    ExpressionNode(kind="operator", value="ts_rank", children=[ExpressionNode(kind="field", value="close"), ExpressionNode(kind="number", value="120")]),
                    ExpressionNode(kind="operator", value="ts_rank", children=[ExpressionNode(kind="field", value="close"), ExpressionNode(kind="number", value="120")]),
                ],
            )
        ],
    )
    candidate = AlphaCandidate(expression=tree.to_expression(), tree=tree, template_type="momentum", params={}, wrappers=["rank"])
    decision = CandidateQualityGate().evaluate(candidate)
    assert decision.should_skip is True
    assert decision.reason in {"identity-subtraction", "duplicate-window-momentum"}


def test_momentum_template_never_uses_same_windows(template_engine):
    candidate = template_engine.instantiate("momentum", {"field_1": "close", "window_1": 20, "window_2": 20, "wrappers": ["rank"]})
    assert candidate.params["window_2"] > candidate.params["window_1"]
