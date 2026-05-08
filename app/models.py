from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import hashlib


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class AlphaCandidate:
    expression: str
    candidate_id: str = ""
    family: str = "manual"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.expression = self.expression.strip()
        if not self.expression:
            raise ValueError("candidate expression is required")
        if not self.candidate_id:
            digest = hashlib.sha1(self.expression.encode("utf-8")).hexdigest()[:12]
            self.candidate_id = f"A_{digest}"


@dataclass
class SimulationHandle:
    simulation_id: str
    submitted_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationMetrics:
    sharpe: Optional[float] = None
    fitness: Optional[float] = None
    returns: Optional[float] = None
    drawdown: Optional[float] = None
    turnover: Optional[float] = None
    margin: Optional[float] = None
    alpha_id: Optional[str] = None
    status: Optional[str] = None
    checks_failed: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "alpha_id": self.alpha_id,
            "status": self.status,
            "sharpe": self.sharpe,
            "fitness": self.fitness,
            "returns": self.returns,
            "drawdown": self.drawdown,
            "turnover": self.turnover,
            "margin": self.margin,
            "checks_failed": self.checks_failed,
            "raw": self.raw,
        }
