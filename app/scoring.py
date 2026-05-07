from __future__ import annotations

from app.models import RewardBreakdown, SimulationMetrics


class ResultScorer:
    def __init__(self, duplicate_penalty: float = 1.0, failure_penalty: float = 2.0) -> None:
        self.duplicate_penalty = duplicate_penalty
        self.failure_penalty = failure_penalty

    def score(self, metrics: SimulationMetrics, duplicate_like: bool = False, failed: bool = False) -> RewardBreakdown:
        fitness_component = metrics.fitness * 0.65
        sharpe_component = metrics.sharpe * 0.30
        extras_component = metrics.returns * 0.08 - metrics.drawdown * 0.03
        check_penalty = self._check_penalty(metrics)
        stability_penalty = self._stage_stability_penalty(metrics)
        penalty = (self.duplicate_penalty if duplicate_like else 0.0) + (self.failure_penalty if failed else 0.0)
        return RewardBreakdown(
            value=fitness_component + sharpe_component + extras_component - penalty - check_penalty - stability_penalty,
            fitness_component=fitness_component,
            sharpe_component=sharpe_component,
            penalty_component=penalty + check_penalty + stability_penalty,
            extras={"returns_component": extras_component, "check_penalty": check_penalty, "stability_penalty": stability_penalty},
        )

    def classify_quality(self, metrics: SimulationMetrics) -> str:
        """Bucket completed simulations for review and template promotion."""
        extras = metrics.extras or {}
        checks_failed = int(extras.get("checks_failed", 0) or 0)
        behavior_similarity = float(extras.get("behavior_similarity", 0.0) or 0.0)
        turnover = metrics.turnover
        region = str(extras.get("region", "USA")).upper()
        delay = int(extras.get("delay", 1) or 1)

        if checks_failed > 0 or behavior_similarity >= 0.7:
            return "low"

        if region == "CHN":
            sharpe_floor = 2.6 if delay == 0 else 1.625
            returns_floor = 0.089 if delay == 0 else 0.063
        else:
            sharpe_floor = 2.0 if delay == 0 else 1.25
            returns_floor = 0.0
        fitness_floor = 1.3 if delay == 0 else 1.0

        passes_submission_floor = (
            metrics.sharpe >= sharpe_floor
            and metrics.fitness >= fitness_floor
            and 0.01 <= turnover <= 0.70
            and abs(metrics.returns) >= returns_floor
        )
        if not passes_submission_floor:
            if metrics.sharpe >= 0.8 and metrics.fitness >= 0.5 and 0.005 <= turnover <= 0.80:
                return "medium"
            return "low"

        if (
            metrics.sharpe >= max(sharpe_floor * 1.25, 1.58)
            and metrics.fitness >= max(fitness_floor * 1.3, 1.3)
            and 0.01 <= turnover <= 0.40
            and behavior_similarity < 0.55
        ):
            return "high"
        return "medium"

    def _check_penalty(self, metrics: SimulationMetrics) -> float:
        checks = metrics.extras.get("checks", [])
        if not isinstance(checks, list):
            return 0.0
        penalty = 0.0
        for check in checks:
            if str(check.get("result", "")).upper() == "FAIL":
                penalty += 0.15
        return penalty

    def _stage_stability_penalty(self, metrics: SimulationMetrics) -> float:
        stage_metrics = metrics.extras.get("stage_metrics", {})
        if not isinstance(stage_metrics, dict) or len(stage_metrics) < 2:
            return 0.0
        sharpe_values = [float(payload.get("sharpe", 0.0)) for payload in stage_metrics.values() if isinstance(payload, dict)]
        fitness_values = [float(payload.get("fitness", 0.0)) for payload in stage_metrics.values() if isinstance(payload, dict)]
        if not sharpe_values and not fitness_values:
            return 0.0
        penalty = 0.0
        if len(sharpe_values) >= 2:
            penalty += max(sharpe_values) - min(sharpe_values)
        if len(fitness_values) >= 2:
            penalty += 0.75 * (max(fitness_values) - min(fitness_values))
        return 0.05 * penalty
