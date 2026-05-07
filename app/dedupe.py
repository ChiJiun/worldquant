from __future__ import annotations

from math import exp
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.models import AlphaCandidate, DedupeDecision, ExpressionNode, SimulationMetrics


def _tokenize(expression: str) -> Set[str]:
    return {token for token in expression.replace("(", " ").replace(")", " ").replace(",", " ").split() if token}


class DedupeService:
    def __init__(self, existing_records: Optional[Iterable[Tuple[str, str, str]]] = None, near_duplicate_threshold: float = 0.82) -> None:
        self.near_duplicate_threshold = near_duplicate_threshold
        self.records = []
        for fingerprint, normalized_expression, template_type in existing_records or []:
            self.records.append(
                {
                    "fingerprint": fingerprint,
                    "normalized_expression": normalized_expression,
                    "template_type": template_type,
                    "signature": ">".join(token for token in _tokenize(normalized_expression) if token.isalpha() or "_" in token),
                    "fields": _tokenize(normalized_expression),
                    "behavior_profile": None,
                }
            )

    def should_skip(self, candidate: AlphaCandidate) -> DedupeDecision:
        tokens = _tokenize(candidate.normalized_expression)
        candidate_signature = self._structure_signature(candidate.tree)
        candidate_fields = self._field_set(candidate.tree)
        for record in self.records:
            if candidate.fingerprint == record["fingerprint"]:
                return DedupeDecision(True, "exact-fingerprint-match", 1.0, record["fingerprint"])
            similarity = self._similarity(tokens, _tokenize(record["normalized_expression"]))
            signature_similarity = self._signature_similarity(candidate_signature, record.get("signature", ""))
            field_similarity = self._similarity(candidate_fields, record.get("fields", set()))
            combined_similarity = 0.45 * similarity + 0.4 * signature_similarity + 0.15 * field_similarity
            effective_similarity = max(similarity, combined_similarity)
            if record["template_type"] == candidate.template_type and effective_similarity >= self.near_duplicate_threshold:
                return DedupeDecision(True, "high-structural-overlap", effective_similarity, record["fingerprint"])
        return DedupeDecision(False, "unique", 0.0, None)

    def register(self, candidate: AlphaCandidate) -> None:
        self.records.append(
            {
                "fingerprint": candidate.fingerprint,
                "normalized_expression": candidate.normalized_expression,
                "template_type": candidate.template_type,
                "signature": self._structure_signature(candidate.tree),
                "fields": self._field_set(candidate.tree),
                "behavior_profile": None,
            }
        )

    def register_behavior(self, candidate: AlphaCandidate, metrics: SimulationMetrics) -> None:
        behavior_profile = self._behavior_profile(metrics)
        for record in self.records:
            if record["fingerprint"] == candidate.fingerprint:
                record["behavior_profile"] = behavior_profile
                return
        self.records.append(
            {
                "fingerprint": candidate.fingerprint,
                "normalized_expression": candidate.normalized_expression,
                "template_type": candidate.template_type,
                "signature": self._structure_signature(candidate.tree),
                "fields": self._field_set(candidate.tree),
                "behavior_profile": behavior_profile,
            }
        )

    def register_existing_behavior(
        self,
        *,
        fingerprint: str,
        normalized_expression: str,
        template_type: str,
        metrics: SimulationMetrics,
    ) -> None:
        behavior_profile = self._behavior_profile(metrics)
        for record in self.records:
            if record["fingerprint"] == fingerprint:
                record["behavior_profile"] = behavior_profile
                return
        self.records.append(
            {
                "fingerprint": fingerprint,
                "normalized_expression": normalized_expression,
                "template_type": template_type,
                "signature": ">".join(token for token in _tokenize(normalized_expression) if token.isalpha() or "_" in token),
                "fields": _tokenize(normalized_expression),
                "behavior_profile": behavior_profile,
            }
        )

    def behavior_similarity(self, candidate: AlphaCandidate, metrics: SimulationMetrics) -> DedupeDecision:
        candidate_profile = self._behavior_profile(metrics)
        best_similarity = 0.0
        best_fingerprint: Optional[str] = None
        for record in self.records:
            if record["fingerprint"] == candidate.fingerprint:
                continue
            behavior_profile = record.get("behavior_profile")
            if not behavior_profile:
                continue
            structural_bias = 0.0
            if record["template_type"] == candidate.template_type:
                structural_bias = 0.05
            similarity = self._behavior_similarity(candidate_profile, behavior_profile) + structural_bias
            if similarity > best_similarity:
                best_similarity = similarity
                best_fingerprint = record["fingerprint"]
        return DedupeDecision(
            should_skip=best_similarity >= 0.92,
            reason="high-behavior-overlap" if best_similarity >= 0.92 else "behavior-unique",
            similarity=min(best_similarity, 1.0),
            matched_fingerprint=best_fingerprint,
        )

    @staticmethod
    def _similarity(left: Set[str], right: Set[str]) -> float:
        if not left and not right:
            return 1.0
        return len(left & right) / max(len(left | right), 1)

    def _signature_similarity(self, left: str, right: str) -> float:
        if not left and not right:
            return 1.0
        left_tokens = set(left.split(">"))
        right_tokens = set(right.split(">"))
        return self._similarity(left_tokens, right_tokens)

    def _structure_signature(self, node: ExpressionNode) -> str:
        parts = []
        self._collect_signature(node, parts)
        return ">".join(parts)

    def _collect_signature(self, node: ExpressionNode, parts: List[str]) -> None:
        if node.kind == "operator" and node.value:
            parts.append(node.value)
        for child in node.children:
            self._collect_signature(child, parts)

    def _field_set(self, node: ExpressionNode) -> Set[str]:
        fields: Set[str] = set()
        self._collect_fields(node, fields)
        return fields

    def _collect_fields(self, node: ExpressionNode, fields: Set[str]) -> None:
        if node.kind == "field" and node.value:
            fields.add(str(node.value))
            return
        for child in node.children:
            self._collect_fields(child, fields)

    def _behavior_profile(self, metrics: SimulationMetrics) -> Dict[str, Any]:
        extras = metrics.extras or {}
        checks = extras.get("checks", [])
        failed_checks = sorted(
            str(check.get("name", check.get("label", "unknown")))
            for check in checks
            if isinstance(check, dict) and str(check.get("result", "")).upper() == "FAIL"
        )
        stage_metrics = extras.get("stage_metrics", {})
        return {
            "values": {
                "sharpe": metrics.sharpe,
                "fitness": metrics.fitness,
                "returns": metrics.returns,
                "drawdown": metrics.drawdown,
                "turnover": metrics.turnover,
                "margin": metrics.margin,
            },
            "failed_checks": failed_checks,
            "stage_metrics": stage_metrics if isinstance(stage_metrics, dict) else {},
            "stage": str(extras.get("stage", "")),
            "universe": str(extras.get("universe", "")),
        }

    def _behavior_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        scales = {
            "sharpe": 1.5,
            "fitness": 1.0,
            "returns": 0.08,
            "drawdown": 0.2,
            "turnover": 0.2,
            "margin": 0.08,
        }
        metric_scores = []
        for key, scale in scales.items():
            diff = abs(float(left["values"].get(key, 0.0)) - float(right["values"].get(key, 0.0)))
            metric_scores.append(exp(-diff / scale))
        check_similarity = self._similarity(set(left.get("failed_checks", [])), set(right.get("failed_checks", [])))
        stage_similarity = self._stage_profile_similarity(left.get("stage_metrics", {}), right.get("stage_metrics", {}))
        universe_similarity = 1.0 if left.get("universe") and left.get("universe") == right.get("universe") else 0.0
        return (0.55 * (sum(metric_scores) / max(len(metric_scores), 1))) + (0.2 * check_similarity) + (0.2 * stage_similarity) + (0.05 * universe_similarity)

    def _stage_profile_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        if not left and not right:
            return 1.0
        score_total = 0.0
        seen = 0
        for stage in sorted(set(left) | set(right)):
            left_stage = left.get(stage, {})
            right_stage = right.get(stage, {})
            if not isinstance(left_stage, dict) or not isinstance(right_stage, dict):
                continue
            stage_scores = []
            for key in ("sharpe", "fitness", "returns", "drawdown"):
                scale = 1.5 if key == "sharpe" else 1.0 if key == "fitness" else 0.08 if key == "returns" else 0.2
                diff = abs(float(left_stage.get(key, 0.0)) - float(right_stage.get(key, 0.0)))
                stage_scores.append(exp(-diff / scale))
            if stage_scores:
                score_total += sum(stage_scores) / len(stage_scores)
                seen += 1
        if seen == 0:
            return 0.0
        return score_total / seen



