from __future__ import annotations

from typing import Dict, List, Set

from app.models import AlphaCandidate, ExpressionNode, QualityDecision


class CandidateQualityGate:
    def evaluate(self, candidate: AlphaCandidate) -> QualityDecision:
        reasons: List[str] = []
        tree = candidate.tree
        if self._contains_identity_subtraction(tree):
            reasons.append("identity-subtraction")
        if self._is_zero_information(tree):
            reasons.append("zero-information-expression")
        if self._has_duplicate_window_momentum(tree):
            reasons.append("duplicate-window-momentum")
        if self._field_diversity(tree) == 0:
            reasons.append("no-fields")
        if reasons:
            return QualityDecision(True, reasons[0], {"reasons": reasons, "expression": candidate.expression})
        return QualityDecision(False, "ok", {"field_count": self._field_diversity(tree)})

    def _contains_identity_subtraction(self, node: ExpressionNode) -> bool:
        if node.kind == "operator" and node.value == "sub" and len(node.children) == 2:
            if node.children[0].normalized().to_expression() == node.children[1].normalized().to_expression():
                return True
        return any(self._contains_identity_subtraction(child) for child in node.children)

    def _is_zero_information(self, node: ExpressionNode) -> bool:
        expression = node.normalized().to_expression()
        return expression in {"0", "(0 - 0)", "rank(0)", "zscore(0)", "ts_rank(0, 20)"}

    def _has_duplicate_window_momentum(self, node: ExpressionNode) -> bool:
        if node.kind == "operator" and node.value == "sub" and len(node.children) == 2:
            left = node.children[0]
            right = node.children[1]
            if left.kind == right.kind == "operator" and left.value == right.value == "ts_rank":
                if left.normalized().to_expression() == right.normalized().to_expression():
                    return True
        return any(self._has_duplicate_window_momentum(child) for child in node.children)

    def _field_diversity(self, node: ExpressionNode) -> int:
        fields: Set[str] = set()
        self._collect_fields(node, fields)
        return len(fields)

    def _collect_fields(self, node: ExpressionNode, fields: Set[str]) -> None:
        if node.kind == "field" and node.value:
            fields.add(node.value)
            return
        for child in node.children:
            self._collect_fields(child, fields)
