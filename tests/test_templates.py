from app.models import AlphaCandidate


def test_template_engine_generates_multiple_template_types(template_engine):
    candidates = template_engine.generate(12)
    assert len(candidates) == 12
    template_types = {candidate.template_type for candidate in candidates}
    assert template_types.issubset(
        {
            "mean_reversion",
            "momentum",
            "price_volume_divergence",
            "fundamental_cross",
            "volatility_reversion",
            "breakout",
            "quality_value",
            "acceleration",
            "range_reversion",
            "quality_efficiency",
            "volume_confirmed_breakout",
            "liquidity_reversal",
            "fundamental_momentum_spread",
        }
    )
    assert all(isinstance(candidate, AlphaCandidate) for candidate in candidates)
    assert all("{" not in candidate.expression for candidate in candidates)


def test_template_engine_honors_template_weights(template_engine):
    candidates = template_engine.generate(8, {"template_weights": {"quality_value": 10.0}, "template_types": ["quality_value"]})
    assert all(candidate.template_type == "quality_value" for candidate in candidates)


def test_normalized_expression_is_stable_for_commutative_nodes():
    from app.models import ExpressionNode

    left = ExpressionNode(kind="operator", value="add", children=[ExpressionNode(kind="field", value="close"), ExpressionNode(kind="field", value="open")])
    right = ExpressionNode(kind="operator", value="add", children=[ExpressionNode(kind="field", value="open"), ExpressionNode(kind="field", value="close")])
    assert left.normalized().to_expression() == right.normalized().to_expression()
    assert left.fingerprint() == right.fingerprint()
