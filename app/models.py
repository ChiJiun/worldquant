from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
import hashlib
import json


COMMUTATIVE_OPS = {"add", "mul", "max", "min"}
INFIX_OPS = {
    "add": "+",
    "sub": "-",
    "mul": "*",
    "div": "/",
}


@dataclass
class ExpressionNode:
    kind: str
    value: Optional[str] = None
    children: List["ExpressionNode"] = field(default_factory=list)

    def to_expression(self) -> str:
        if self.kind in {"field", "number", "raw"}:
            return str(self.value)
        if self.value in INFIX_OPS and len(self.children) == 2:
            left = self.children[0].to_expression()
            right = self.children[1].to_expression()
            return f"({left} {INFIX_OPS[self.value]} {right})"
        args = ", ".join(child.to_expression() for child in self.children)
        return f"{self.value}({args})"

    def normalized(self) -> "ExpressionNode":
        if self.kind in {"field", "number"}:
            return ExpressionNode(kind=self.kind, value=str(self.value))
        normalized_children = [child.normalized() for child in self.children]
        if self.value in COMMUTATIVE_OPS:
            normalized_children = sorted(normalized_children, key=lambda item: item.to_expression())
        return ExpressionNode(kind=self.kind, value=self.value, children=normalized_children)

    def fingerprint(self) -> str:
        payload = self._fingerprint_payload(self.normalized())
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _fingerprint_payload(cls, node: "ExpressionNode") -> str:
        if node.kind in {"field", "number", "raw"}:
            value = str(node.value)
            if node.kind == "number":
                return f"number:{value}|bucket:{cls._bucket_number(value)}"
            if node.kind == "raw":
                return f"raw:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
            return f"field:{value}"
        child_payload = ",".join(cls._fingerprint_payload(child) for child in node.children)
        return f"{node.value}[{child_payload}]"

    @staticmethod
    def _bucket_number(value: str) -> str:
        try:
            number = float(value)
        except ValueError:
            return value
        if number <= 5:
            return "tiny"
        if number <= 20:
            return "short"
        if number <= 60:
            return "medium"
        return "long"


@dataclass
class AlphaCandidate:
    expression: str
    tree: ExpressionNode
    template_type: str
    params: Dict[str, Any]
    wrappers: List[str] = field(default_factory=list)
    candidate_id: Optional[int] = None

    @property
    def normalized_expression(self) -> str:
        return self.tree.normalized().to_expression()

    @property
    def fingerprint(self) -> str:
        return self.tree.fingerprint()


@dataclass
class SimulationMetrics:
    sharpe: float = 0.0
    fitness: float = 0.0
    returns: float = 0.0
    drawdown: float = 0.0
    turnover: float = 0.0
    margin: float = 0.0
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RewardBreakdown:
    value: float
    fitness_component: float
    sharpe_component: float
    penalty_component: float
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationHandle:
    simulation_id: str
    submitted_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationRecord:
    candidate: AlphaCandidate
    handle: Optional[SimulationHandle]
    metrics: SimulationMetrics
    reward: RewardBreakdown
    api_status: str
    error: Optional[str] = None
    completed_at: Optional[datetime] = None


@dataclass
class DedupeDecision:
    should_skip: bool
    reason: str
    similarity: float = 0.0
    matched_fingerprint: Optional[str] = None


@dataclass
class SearchObservation:
    candidate: AlphaCandidate
    reward: RewardBreakdown
    metrics: SimulationMetrics
    status: str


@dataclass
class QualityDecision:
    should_skip: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


def json_dumps(data: Sequence[Any]) -> str:
    return json.dumps(list(data), ensure_ascii=True, sort_keys=True)
