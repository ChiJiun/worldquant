from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time

from app.api import RateLimiter, build_client
from app.config import Settings
from app.models import AlphaCandidate, ExpressionNode, SimulationMetrics, SimulationRecord
from app.scoring import ResultScorer
from app.storage import StorageRepository


@dataclass
class WorkflowAlpha:
    hypothesis_id: str
    expression: str
    family: str
    rationale: str = ""


class AlphaDiscoveryWorkflow:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_directories()
        self.storage = StorageRepository(settings.storage_path, settings.output_dir)
        self.client = build_client(settings, RateLimiter(settings.rate_limit_seconds))
        self.scorer = ResultScorer()

    def close(self) -> None:
        self.storage.close()

    def run(self, hypotheses_path: Path, *, promote: bool = False) -> Path:
        payload = json.loads(hypotheses_path.read_text(encoding="utf-8"))
        self._save_hypotheses(payload)
        alphas = self._load_alphas(payload)
        records: List[SimulationRecord] = []
        for alpha in alphas:
            records.append(self._simulate_alpha(alpha))
        report_path = self._write_report(hypotheses_path, records, promote=promote)
        if promote:
            self._write_promotable_families(records)
        return report_path

    def _save_hypotheses(self, payload: Dict[str, Any]) -> None:
        session_id = str(payload.get("session_id") or "")
        for hypothesis in payload.get("hypotheses", []):
            self.storage.save_research_hypothesis(session_id, hypothesis)

    def _load_alphas(self, payload: Dict[str, Any]) -> List[WorkflowAlpha]:
        loaded: List[WorkflowAlpha] = []
        for hypothesis in payload.get("hypotheses", []):
            hypothesis_id = str(hypothesis.get("id") or hypothesis.get("name") or f"hypothesis_{len(loaded) + 1}")
            family = str(hypothesis.get("family") or hypothesis_id)
            rationale = str(hypothesis.get("rationale") or hypothesis.get("economic_mechanism") or "")
            for item in hypothesis.get("alphas", []):
                expression = str(item.get("expression") or item.get("code") or "").strip()
                if not expression:
                    continue
                loaded.append(
                    WorkflowAlpha(
                        hypothesis_id=hypothesis_id,
                        expression=expression,
                        family=str(item.get("family") or family),
                        rationale=str(item.get("rationale") or rationale),
                    )
                )
        if not loaded:
            raise ValueError("No alpha expressions found. Expected hypotheses[].alphas[].expression in the input JSON.")
        return loaded

    def _simulate_alpha(self, alpha: WorkflowAlpha) -> SimulationRecord:
        candidate = AlphaCandidate(
            expression=alpha.expression,
            tree=ExpressionNode(kind="raw", value=alpha.expression),
            template_type=alpha.family,
            params={"hypothesis_id": alpha.hypothesis_id, "rationale": alpha.rationale},
            wrappers=[],
        )
        alpha_id = self.storage.save_candidate(candidate, status="queued")
        try:
            handle = self.client.simulate(candidate, {"mode": "research", "dry_run": self.settings.dry_run})
            terminal = self._wait_for_completion(handle.simulation_id)
            status = str(terminal.get("status", "complete")).lower()
            result_id = str(terminal.get("alpha") or handle.simulation_id)
            metrics = self.client.fetch_result(result_id)
            metrics.extras["triage_decision"] = self.scorer.triage_decision(metrics)
            metrics.extras["quality_tier"] = self.scorer.classify_quality(metrics)
            metrics.extras["hypothesis_id"] = alpha.hypothesis_id
            metrics.extras["family"] = alpha.family
            reward = self.scorer.score(metrics)
            is_best = metrics.extras["triage_decision"] == "submit_ready"
            record = SimulationRecord(
                candidate=candidate,
                handle=handle,
                metrics=metrics,
                reward=reward,
                api_status=status,
                completed_at=datetime.now(timezone.utc),
            )
            self.storage.mark_status(alpha_id, "complete")
            self.storage.save_result(alpha_id, record, is_best=is_best)
            self.storage.append_run_summary(record)
            self._record_template_decision(alpha, candidate, metrics, source="research_workflow")
            if is_best:
                self.storage.save_submittable_alpha(candidate, metrics, source="research_workflow")
                self.storage.append_best_alpha(candidate, metrics, reward)
            return record
        except Exception as exc:
            self.storage.mark_status(alpha_id, "failed")
            metrics = SimulationMetrics(extras={"triage_decision": "reject", "quality_tier": "not_submittable", "hypothesis_id": alpha.hypothesis_id, "family": alpha.family})
            record = SimulationRecord(
                candidate=candidate,
                handle=None,
                metrics=metrics,
                reward=self.scorer.score(metrics, failed=True),
                api_status="failed",
                error=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
            self.storage.save_result(alpha_id, record, is_best=False)
            self.storage.append_failure(candidate, str(exc))
            return record

    def _record_template_decision(self, alpha: WorkflowAlpha, candidate: AlphaCandidate, metrics: SimulationMetrics, source: str) -> None:
        decision = str((metrics.extras or {}).get("triage_decision", "reject"))
        if decision == "reject":
            return
        status = "candidate" if decision == "refine_candidate" else "submit_ready"
        self.storage.save_alpha_template(
            family=alpha.family,
            hypothesis_id=alpha.hypothesis_id,
            seed_expression=candidate.expression,
            rationale=alpha.rationale,
            source=source,
            status=status,
            triage_decision=decision,
            quality_tier=str((metrics.extras or {}).get("quality_tier", "")),
            metrics=self.storage._metrics_payload(metrics),
        )

    def _wait_for_completion(self, simulation_id: str) -> Dict[str, Any]:
        for _ in range(self.settings.max_poll_attempts):
            payload = self.client.poll(simulation_id)
            status = str(payload.get("status", "unknown")).lower()
            if status in {"complete", "completed", "done"}:
                return payload
            if status in {"failed", "error", "cancelled"}:
                raise RuntimeError(f"Simulation failed with status: {status}")
            time.sleep(self.settings.poll_interval_seconds)
        raise TimeoutError(f"Simulation {simulation_id} timed out")

    def _write_report(self, hypotheses_path: Path, records: List[SimulationRecord], *, promote: bool) -> Path:
        report_path = self.settings.output_dir / f"alpha_workflow_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        lines = [
            "# Alpha Discovery Workflow Report",
            "",
            f"- input: `{hypotheses_path}`",
            f"- promote: `{promote}`",
            f"- total: {len(records)}",
            "",
            "| decision | tier | status | family | sharpe | fitness | turnover | checks_failed | reward | expression |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for record in sorted(records, key=lambda item: item.reward.value, reverse=True):
            extras = record.metrics.extras or {}
            lines.append(
                "| {decision} | {tier} | {status} | {family} | {sharpe:.4f} | {fitness:.4f} | {turnover:.4f} | {checks} | {reward:.4f} | `{expr}` |".format(
                    decision=extras.get("triage_decision", "reject"),
                    tier=extras.get("quality_tier", "low"),
                    status=record.api_status,
                    family=record.candidate.template_type,
                    sharpe=record.metrics.sharpe,
                    fitness=record.metrics.fitness,
                    turnover=record.metrics.turnover,
                    checks=extras.get("checks_failed", 0),
                    reward=record.reward.value,
                    expr=record.candidate.expression.replace("|", "\\|"),
                )
            )
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report_path

    def _write_promotable_families(self, records: List[SimulationRecord]) -> None:
        rows = [
            {
                "family": record.candidate.template_type,
                "expression": record.candidate.expression,
                "triage_decision": (record.metrics.extras or {}).get("triage_decision", ""),
                "quality_tier": (record.metrics.extras or {}).get("quality_tier", ""),
                "sharpe": record.metrics.sharpe,
                "fitness": record.metrics.fitness,
                "turnover": record.metrics.turnover,
                "rationale": record.candidate.params.get("rationale", ""),
            }
            for record in records
            if (record.metrics.extras or {}).get("triage_decision") in {"submit_ready", "refine_candidate"}
        ]
        path = self.settings.output_dir / "promotable_families.json"
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=True), encoding="utf-8")
