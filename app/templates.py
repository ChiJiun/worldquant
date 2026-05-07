from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
import random

from app.models import AlphaCandidate, ExpressionNode


@dataclass
class TemplateDefinition:
    name: str
    fields: Sequence[str]
    windows: Sequence[int]
    wrappers: Sequence[str]


class TemplateEngine:
    def __init__(self, field_catalog: Dict[str, Any], template_specs: Dict[str, Any], seed: int = 7) -> None:
        self.random = random.Random(seed)
        self.templates = {
            name: TemplateDefinition(
                name=name,
                fields=spec["fields"],
                windows=spec["windows"],
                wrappers=spec.get("wrappers", field_catalog.get("wrappers", [])),
            )
            for name, spec in template_specs.items()
        }
        self.group_fields = field_catalog.get("group_fields", ["sector"])
        self.decays = field_catalog.get("decays", [3, 5, 10])

    def generate(self, seed_count: int, constraints: Optional[Dict[str, Any]] = None) -> List[AlphaCandidate]:
        if not self.templates:
            raise ValueError(
                "No alpha templates are configured. Add vetted family templates to config/templates.json "
                "before running GA/search."
            )
        constraints = constraints or {}
        template_names = constraints.get("template_types") or list(self.templates.keys())
        template_weights = constraints.get("template_weights") or {}
        template_names = [name for name in template_names if name in self.templates]
        if not template_names:
            raise ValueError("No active alpha templates match the current whitelist/blacklist constraints.")
        return [self.instantiate(self._choose_template(template_names, template_weights)) for _ in range(seed_count)]

    def instantiate(self, template_name: str, params: Optional[Dict[str, Any]] = None) -> AlphaCandidate:
        params = dict(params or {})
        if template_name not in self.templates:
            raise ValueError(f"Unknown alpha template: {template_name}")
        template = self.templates[template_name]
        builders = {
            "mean_reversion": self._build_mean_reversion,
            "momentum": self._build_momentum,
            "price_volume_divergence": self._build_price_volume_divergence,
            "fundamental_cross": self._build_fundamental_cross,
            "volatility_reversion": self._build_volatility_reversion,
            "breakout": self._build_breakout,
            "quality_value": self._build_quality_value,
            "acceleration": self._build_acceleration,
            "range_reversion": self._build_range_reversion,
            "quality_efficiency": self._build_quality_efficiency,
            "volume_confirmed_breakout": self._build_volume_confirmed_breakout,
            "liquidity_reversal": self._build_liquidity_reversal,
            "fundamental_momentum_spread": self._build_fundamental_momentum_spread,
        }
        return builders[template_name](template, params)

    def mutate_candidate(self, candidate: AlphaCandidate) -> AlphaCandidate:
        params = dict(candidate.params)
        definition = self.templates[candidate.template_type]
        mutation = self.random.choice(["field", "window", "wrapper", "decay", "template"])
        if mutation == "field":
            keys = [key for key in params if "field" in key]
            if keys:
                params[self.random.choice(keys)] = self.random.choice(definition.fields)
        elif mutation == "window":
            keys = [key for key in params if "window" in key]
            if keys:
                params[self.random.choice(keys)] = self.random.choice(definition.windows)
        elif mutation == "wrapper" and candidate.wrappers:
            wrappers = list(candidate.wrappers)
            wrappers[self.random.randrange(len(wrappers))] = self.random.choice(definition.wrappers)
            params["wrappers"] = wrappers
        elif mutation == "decay" and "decay" in params:
            params["decay"] = self.random.choice(self.decays)
        elif mutation == "template":
            return self.instantiate(self.random.choice(list(self.templates.keys())))
        return self.instantiate(candidate.template_type, params)

    def crossover(self, left: AlphaCandidate, right: AlphaCandidate) -> AlphaCandidate:
        template_name = self.random.choice([left.template_type, right.template_type])
        merged: Dict[str, Any] = {}
        for key in set(left.params) | set(right.params):
            values = [params[key] for params in (left.params, right.params) if key in params]
            merged[key] = self.random.choice(values)
        wrappers = list(left.wrappers) + list(right.wrappers)
        if wrappers:
            merged["wrappers"] = [self.random.choice(wrappers)]
        return self.instantiate(template_name, merged)

    def _pick(self, current: Dict[str, Any], key: str, options: Sequence[Any]) -> Any:
        return current.get(key, self.random.choice(list(options)))

    def _choose_template(self, template_names: Sequence[str], template_weights: Dict[str, float]) -> str:
        weights = [max(template_weights.get(name, 1.0), 0.01) for name in template_names]
        return self.random.choices(list(template_names), weights=weights, k=1)[0]

    def _wrap(self, node: ExpressionNode, wrappers: Sequence[str], params: Dict[str, Any]) -> ExpressionNode:
        wrapped = node
        for wrapper in wrappers:
            if wrapper in {"rank", "zscore"}:
                wrapped = ExpressionNode(kind="operator", value=wrapper, children=[wrapped])
            elif wrapper in {"ts_rank", "ts_decay_linear"}:
                wrapped = ExpressionNode(
                    kind="operator",
                    value=wrapper,
                    children=[wrapped, ExpressionNode(kind="number", value=str(params.get("window_1", 20)))],
                )
        return wrapped

    def _build_mean_reversion(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        group = self._pick(params, "group", self.group_fields)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="group_neutralize",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="sub",
                    children=[
                        ExpressionNode(kind="field", value=field),
                        ExpressionNode(
                            kind="operator",
                            value="ts_mean",
                            children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                        ),
                    ],
                ),
                ExpressionNode(kind="field", value=group),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": window, "group": group}, wrappers)

    def _build_momentum(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        fast = self._pick(params, "window_1", definition.windows)
        valid_slow = [value for value in definition.windows if value > fast]
        slow = params.get("window_2", self.random.choice(valid_slow or definition.windows))
        if slow <= fast:
            slow = valid_slow[0] if valid_slow else max(definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(fast))],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(slow))],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": fast})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": fast, "window_2": slow}, wrappers)

    def _build_price_volume_divergence(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        price_field = self._pick(params, "field_1", [value for value in definition.fields if value not in {"volume", "adv20"}])
        volume_field = self._pick(params, "field_2", [value for value in definition.fields if value in {"volume", "adv20"}] or definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        decay = self._pick(params, "decay", self.decays)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_delta",
                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(window))],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_decay_linear",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="ts_delta",
                            children=[ExpressionNode(kind="field", value=volume_field), ExpressionNode(kind="number", value=str(window))],
                        ),
                        ExpressionNode(kind="number", value=str(decay)),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(
            tree.to_expression(),
            tree,
            definition.name,
            {"field_1": price_field, "field_2": volume_field, "window_1": window, "decay": decay},
            wrappers,
        )

    def _build_fundamental_cross(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        left = self._pick(params, "field_1", definition.fields)
        right = self._pick(params, "field_2", [value for value in definition.fields if value != left] or definition.fields)
        if right == left:
            alternatives = [value for value in definition.fields if value != left]
            right = self.random.choice(alternatives) if alternatives else right
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=left), ExpressionNode(kind="number", value=str(window))],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=right), ExpressionNode(kind="number", value=str(window))],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": left, "field_2": right, "window_1": window}, wrappers)

    def _build_volatility_reversion(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="div",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="sub",
                    children=[
                        ExpressionNode(kind="field", value=field),
                        ExpressionNode(
                            kind="operator",
                            value="ts_mean",
                            children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                        ),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="add",
                    children=[
                        ExpressionNode(kind="number", value="1"),
                        ExpressionNode(
                            kind="operator",
                            value="ts_std_dev",
                            children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                        ),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": window}, wrappers)

    def _build_breakout(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="div",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="sub",
                    children=[
                        ExpressionNode(kind="field", value=field),
                        ExpressionNode(
                            kind="operator",
                            value="ts_min",
                            children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                        ),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="add",
                    children=[
                        ExpressionNode(kind="number", value="1"),
                        ExpressionNode(
                            kind="operator",
                            value="sub",
                            children=[
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_max",
                                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                                ),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_min",
                                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": window}, wrappers)

    def _build_quality_value(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        left = self._pick(params, "field_1", definition.fields)
        right = self._pick(params, "field_2", [value for value in definition.fields if value != left] or definition.fields)
        if right == left:
            alternatives = [value for value in definition.fields if value != left]
            right = self.random.choice(alternatives) if alternatives else right
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="div",
                            children=[
                                ExpressionNode(kind="field", value=left),
                                ExpressionNode(
                                    kind="operator",
                                    value="add",
                                    children=[ExpressionNode(kind="number", value="1"), ExpressionNode(kind="field", value=right)],
                                ),
                            ],
                        ),
                        ExpressionNode(kind="number", value=str(window)),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=right), ExpressionNode(kind="number", value=str(window))],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": left, "field_2": right, "window_1": window}, wrappers)

    def _build_acceleration(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        short_window = self._pick(params, "window_1", definition.windows)
        long_candidates = [value for value in definition.windows if value > short_window]
        long_window = params.get("window_2", self.random.choice(long_candidates or definition.windows))
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_delta",
                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(short_window))],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_delta",
                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(long_window))],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": short_window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": short_window, "window_2": long_window}, wrappers)

    def _build_range_reversion(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        field = self._pick(params, "field_1", definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="div",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="sub",
                    children=[
                        ExpressionNode(kind="field", value=field),
                        ExpressionNode(
                            kind="operator",
                            value="ts_mean",
                            children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                        ),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="add",
                    children=[
                        ExpressionNode(kind="number", value="1"),
                        ExpressionNode(
                            kind="operator",
                            value="sub",
                            children=[
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_max",
                                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                                ),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_min",
                                    children=[ExpressionNode(kind="field", value=field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": field, "window_1": window}, wrappers)

    def _build_quality_efficiency(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        left = self._pick(params, "field_1", definition.fields)
        right = self._pick(params, "field_2", [value for value in definition.fields if value != left] or definition.fields)
        if right == left:
            alternatives = [value for value in definition.fields if value != left]
            right = self.random.choice(alternatives) if alternatives else right
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="div",
                            children=[
                                ExpressionNode(kind="field", value=left),
                                ExpressionNode(
                                    kind="operator",
                                    value="add",
                                    children=[ExpressionNode(kind="number", value="1"), ExpressionNode(kind="field", value=right)],
                                ),
                            ],
                        ),
                        ExpressionNode(kind="number", value=str(window)),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="div",
                            children=[
                                ExpressionNode(kind="field", value=right),
                                ExpressionNode(
                                    kind="operator",
                                    value="add",
                                    children=[ExpressionNode(kind="number", value="1"), ExpressionNode(kind="field", value=left)],
                                ),
                            ],
                        ),
                        ExpressionNode(kind="number", value=str(window)),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(tree.to_expression(), tree, definition.name, {"field_1": left, "field_2": right, "window_1": window}, wrappers)

    def _build_volume_confirmed_breakout(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        price_field = self._pick(params, "field_1", [value for value in definition.fields if value not in {"volume", "adv20", "adv60"}])
        volume_field = self._pick(params, "field_2", [value for value in definition.fields if value in {"volume", "adv20", "adv60"}] or definition.fields)
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="mul",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="div",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="sub",
                            children=[
                                ExpressionNode(kind="field", value=price_field),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_max",
                                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                        ExpressionNode(
                            kind="operator",
                            value="add",
                            children=[
                                ExpressionNode(kind="number", value="1"),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_std_dev",
                                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                    ],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=volume_field), ExpressionNode(kind="number", value=str(window))],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(
            tree.to_expression(),
            tree,
            definition.name,
            {"field_1": price_field, "field_2": volume_field, "window_1": window},
            wrappers,
        )

    def _build_liquidity_reversal(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        price_field = self._pick(params, "field_1", [value for value in definition.fields if value not in {"volume", "adv20", "adv60"}])
        liquidity_field = self._pick(params, "field_2", [value for value in definition.fields if value in {"volume", "adv20", "adv60"}] or definition.fields)
        group = self._pick(params, "group", self.group_fields)
        window = self._pick(params, "window_1", definition.windows)
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="group_neutralize",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="div",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="sub",
                            children=[
                                ExpressionNode(kind="field", value=price_field),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_mean",
                                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                        ExpressionNode(
                            kind="operator",
                            value="add",
                            children=[
                                ExpressionNode(kind="number", value="1"),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_rank",
                                    children=[ExpressionNode(kind="field", value=liquidity_field), ExpressionNode(kind="number", value=str(window))],
                                ),
                            ],
                        ),
                    ],
                ),
                ExpressionNode(kind="field", value=group),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": window})
        return AlphaCandidate(
            tree.to_expression(),
            tree,
            definition.name,
            {"field_1": price_field, "field_2": liquidity_field, "window_1": window, "group": group},
            wrappers,
        )

    def _build_fundamental_momentum_spread(self, definition: TemplateDefinition, params: Dict[str, Any]) -> AlphaCandidate:
        fundamental_field = self._pick(params, "field_1", [value for value in definition.fields if value not in {"close", "returns", "vwap"}] or definition.fields)
        price_field = self._pick(params, "field_2", [value for value in definition.fields if value in {"close", "returns", "vwap"}] or definition.fields)
        short_window = self._pick(params, "window_1", definition.windows)
        long_candidates = [value for value in definition.windows if value > short_window]
        long_window = params.get("window_2", self.random.choice(long_candidates or definition.windows))
        wrappers = list(params.get("wrappers", [self.random.choice(definition.wrappers)]))
        base = ExpressionNode(
            kind="operator",
            value="sub",
            children=[
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[ExpressionNode(kind="field", value=fundamental_field), ExpressionNode(kind="number", value=str(long_window))],
                ),
                ExpressionNode(
                    kind="operator",
                    value="ts_rank",
                    children=[
                        ExpressionNode(
                            kind="operator",
                            value="sub",
                            children=[
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_rank",
                                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(short_window))],
                                ),
                                ExpressionNode(
                                    kind="operator",
                                    value="ts_rank",
                                    children=[ExpressionNode(kind="field", value=price_field), ExpressionNode(kind="number", value=str(long_window))],
                                ),
                            ],
                        ),
                        ExpressionNode(kind="number", value=str(short_window)),
                    ],
                ),
            ],
        )
        tree = self._wrap(base, wrappers, {"window_1": short_window})
        return AlphaCandidate(
            tree.to_expression(),
            tree,
            definition.name,
            {"field_1": fundamental_field, "field_2": price_field, "window_1": short_window, "window_2": long_window},
            wrappers,
        )
