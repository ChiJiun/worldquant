from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time
from typing import Dict, List, Optional

from app.api import BrainClient
from app.config import Settings
from app.dedupe import DedupeService
from app.models import AlphaCandidate, SearchObservation, SimulationMetrics, SimulationRecord
from app.quality import CandidateQualityGate
from app.scoring import ResultScorer
from app.search import SearchEngine
from app.storage import StorageRepository
from app.templates import TemplateEngine

LOGGER = logging.getLogger(__name__)
EVENT_LOGGER = logging.getLogger("events")


class AlphaPipeline:
    def __init__(
        self,
        settings: Settings,
        template_engine: TemplateEngine,
        search_engine: SearchEngine,
        storage: StorageRepository,
        client: BrainClient,
        scorer: ResultScorer,
        dedupe: DedupeService,
    ) -> None:
        self.settings = settings
        self.template_engine = template_engine
        self.search_engine = search_engine
        self.storage = storage
        self.client = client
        self.scorer = scorer
        self.dedupe = dedupe
        self.quality_gate = CandidateQualityGate()
        self._checkpoint_overrides: Dict[str, object] = {}
        self._bootstrap_behavior_profiles()

    def generate_only(self, count: int) -> List[AlphaCandidate]:
        candidates = self.template_engine.generate(count)
        for candidate in candidates:
            alpha_id = self.storage.save_candidate(candidate, status="generated")
            EVENT_LOGGER.info("generated alpha_id=%s template=%s", alpha_id, candidate.template_type)
        return candidates

    def run_search(self, generations: Optional[int] = None) -> List[SimulationRecord]:
        self.search_engine.initialize(
            seed_candidates=self._load_seed_candidates(),
            constraints=self._build_generation_constraints(),
        )
        history: List[SearchObservation] = []
        results: List[SimulationRecord] = []
        total_generations = generations or self.settings.generations
        for generation in range(total_generations):
            LOGGER.info("Running generation %s/%s", generation + 1, total_generations)
            batch = self.search_engine.next_batch(history if generation else [], self.settings.batch_size)
            history = []
            for candidate in batch:
                record = self._process_candidate(candidate)
                results.append(record)
                history.append(
                    SearchObservation(
                        candidate=candidate,
                        reward=record.reward,
                        metrics=record.metrics,
                        status=record.api_status,
                    )
                )
        return results

    def run_mining_session(self, cycles: Optional[int] = None, sleep_seconds: Optional[float] = None) -> List[SimulationRecord]:
        return self._run_mining_session(
            total_cycles=cycles or self.settings.mine_cycles,
            sleep_seconds=self.settings.mine_sleep_seconds if sleep_seconds is None else sleep_seconds,
            session_id=None,
            initial_checkpoint=None,
            prior_totals=None,
        )

    def _run_mining_session(
        self,
        *,
        total_cycles: int,
        sleep_seconds: float,
        session_id: Optional[int],
        initial_checkpoint: Optional[Dict[str, object]],
        prior_totals: Optional[Dict[str, float]],
    ) -> List[SimulationRecord]:
        delay = sleep_seconds
        all_results: List[SimulationRecord] = []
        if session_id is None:
            session_id = self.storage.start_session(total_cycles)
        checkpoint_state = dict(initial_checkpoint or {})
        self._checkpoint_overrides = dict(checkpoint_state)
        totals = {
            "submitted_count": float((prior_totals or {}).get("submitted_count", 0.0)),
            "completed_count": float((prior_totals or {}).get("completed_count", 0.0)),
            "best_count": float((prior_totals or {}).get("best_count", 0.0)),
            "reward_sum": float((prior_totals or {}).get("reward_sum", 0.0)),
        }
        for cycle in range(total_cycles):
            LOGGER.info("Starting mining cycle %s/%s", cycle + 1, total_cycles)
            cycle_results = self.run_search(self.settings.generations)
            all_results.extend(cycle_results)
            summary = self._summarize_cycle(cycle_results)
            totals["submitted_count"] += summary["submitted"]
            totals["completed_count"] += summary["completed"]
            totals["best_count"] += summary["best"]
            totals["reward_sum"] += sum(record.reward.value for record in cycle_results)
            governance = self._build_generation_constraints()
            checkpoint = {
                "last_cycle": checkpoint_state.get("last_cycle", 0) + 1,
                "template_weights": governance.get("template_weights", {}),
                "active_templates": governance.get("template_types", []),
                "auto_blacklist": governance.get("auto_blacklist", []),
                "auto_whitelist": governance.get("auto_whitelist", []),
                "failure_summary": self._build_failure_summary(),
            }
            self.storage.update_session(
                session_id,
                cycles_completed=int(checkpoint["last_cycle"]),
                submitted_count=int(totals["submitted_count"]),
                completed_count=int(totals["completed_count"]),
                best_count=int(totals["best_count"]),
                avg_reward=totals["reward_sum"] / max(totals["submitted_count"], 1.0),
                checkpoint=checkpoint,
            )
            LOGGER.info(
                "Cycle %s complete: submitted=%s complete=%s best=%s avg_reward=%.4f",
                cycle + 1,
                summary["submitted"],
                summary["completed"],
                summary["best"],
                summary["avg_reward"],
            )
            if (cycle + 1) % max(self.settings.checkpoint_every_cycles, 1) == 0:
                LOGGER.info("Checkpoint saved for session=%s cycle=%s", session_id, cycle + 1)
            dashboard_path = self.storage.generate_session_dashboard()
            LOGGER.info("Session dashboard updated path=%s", dashboard_path)
            checkpoint_state = checkpoint
            self._checkpoint_overrides = dict(checkpoint_state)
            if cycle < total_cycles - 1 and delay > 0:
                time.sleep(delay)
        self.storage.finish_session(session_id)
        self._checkpoint_overrides = {}
        return all_results

    def resume_mining_session(self, sleep_seconds: Optional[float] = None) -> List[SimulationRecord]:
        checkpoint_row = self.storage.load_latest_checkpoint()
        if not checkpoint_row:
            LOGGER.info("No checkpoint found; starting a fresh mining session")
            return self.run_mining_session(self.settings.mine_cycles, sleep_seconds)
        cycles_planned = int(checkpoint_row["cycles_planned"])
        cycles_completed = int(checkpoint_row["cycles_completed"])
        remaining = max(cycles_planned - cycles_completed, 1)
        checkpoint_payload = json.loads(checkpoint_row["checkpoint_json"] or "{}")
        LOGGER.info(
            "Resuming from checkpoint session=%s cycles_completed=%s cycles_planned=%s remaining=%s",
            checkpoint_row["id"],
            cycles_completed,
            cycles_planned,
            remaining,
        )
        return self._run_mining_session(
            total_cycles=remaining,
            sleep_seconds=self.settings.mine_sleep_seconds if sleep_seconds is None else sleep_seconds,
            session_id=int(checkpoint_row["id"]) if checkpoint_row["ended_at"] is None else None,
            initial_checkpoint=checkpoint_payload,
            prior_totals={
                "submitted_count": float(checkpoint_row["submitted_count"] or 0.0),
                "completed_count": float(checkpoint_row["completed_count"] or 0.0),
                "best_count": float(checkpoint_row["best_count"] or 0.0),
                "reward_sum": float(checkpoint_row["avg_reward"] or 0.0) * max(float(checkpoint_row["submitted_count"] or 0.0), 0.0),
            },
        )

    def retry_failed(self) -> List[SimulationRecord]:
        retried: List[SimulationRecord] = []
        for row in self.storage.list_failed():
            candidate = self.template_engine.instantiate(row["template_type"])
            candidate.expression = row["expression"]
            record = self._process_candidate(candidate, allow_duplicate=True)
            retried.append(record)
        return retried

    def _process_candidate(self, candidate: AlphaCandidate, allow_duplicate: bool = False) -> SimulationRecord:
        alpha_id = self.storage.save_candidate(candidate, status="queued")
        quality_decision = self.quality_gate.evaluate(candidate)
        if quality_decision.should_skip:
            self.storage.mark_status(alpha_id, "filtered")
            reward = self.scorer.score(SimulationMetrics(), failed=True)
            record = SimulationRecord(
                candidate=candidate,
                handle=None,
                metrics=SimulationMetrics(),
                reward=reward,
                api_status="filtered",
                error=quality_decision.reason,
                completed_at=datetime.now(timezone.utc),
            )
            self.storage.save_result(alpha_id, record, is_best=False)
            self.storage.append_failure(candidate, quality_decision.reason)
            LOGGER.info("Filtered low-quality candidate template=%s reason=%s expression=%s", candidate.template_type, quality_decision.reason, candidate.expression)
            return record
        decision = self.dedupe.should_skip(candidate)
        if decision.should_skip and not allow_duplicate:
            self.storage.mark_status(alpha_id, "duplicate")
            reward = self.scorer.score(SimulationMetrics(), duplicate_like=True, failed=True)
            record = SimulationRecord(candidate=candidate, handle=None, metrics=SimulationMetrics(), reward=reward, api_status="duplicate", error=decision.reason, completed_at=datetime.now(timezone.utc))
            self.storage.save_result(alpha_id, record, is_best=False)
            self.storage.append_failure(candidate, decision.reason)
            return record
        self.dedupe.register(candidate)
        try:
            LOGGER.info(
                "Preparing simulation template=%s expression=%s",
                candidate.template_type,
                candidate.expression,
            )
            EVENT_LOGGER.info(
                "preparing template=%s expression=%s",
                candidate.template_type,
                candidate.expression,
            )
            handle = self.client.simulate(candidate, {"mode": "research", "dry_run": self.settings.dry_run})
            LOGGER.info(
                "Simulation accepted template=%s simulation_id=%s",
                candidate.template_type,
                handle.simulation_id,
            )
            terminal = self._wait_for_completion(handle.simulation_id)
            status = str(terminal.get("status", "complete")).lower()
            result_id = str(terminal.get("alpha") or handle.simulation_id)
            metrics = self.client.fetch_result(result_id)
            behavior_decision = self.dedupe.behavior_similarity(candidate, metrics)
            metrics.extras["behavior_similarity"] = behavior_decision.similarity
            metrics.extras["behavior_overlap_reason"] = behavior_decision.reason
            metrics.extras["quality_tier"] = self.scorer.classify_quality(metrics)
            reward = self.scorer.score(metrics, duplicate_like=behavior_decision.should_skip)
            completed_at = datetime.now(timezone.utc)
            is_best = (
                metrics.sharpe > self.settings.sharpe_threshold
                and metrics.fitness > self.settings.fitness_threshold
                and not behavior_decision.should_skip
            )
            self.storage.mark_status(alpha_id, "complete")
            record = SimulationRecord(candidate=candidate, handle=handle, metrics=metrics, reward=reward, api_status=status, completed_at=completed_at)
            self.storage.save_result(alpha_id, record, is_best=is_best)
            self.storage.append_run_summary(record)
            if is_best:
                self.storage.append_best_alpha(candidate, metrics)
            self.dedupe.register_behavior(candidate, metrics)
            EVENT_LOGGER.info("completed alpha_id=%s status=%s sharpe=%.4f fitness=%.4f", alpha_id, status, metrics.sharpe, metrics.fitness)
            LOGGER.info(
                "Simulation completed simulation_id=%s alpha_id=%s sharpe=%.4f fitness=%.4f returns=%.4f drawdown=%.4f behavior_similarity=%.4f",
                handle.simulation_id,
                result_id,
                metrics.sharpe,
                metrics.fitness,
                metrics.returns,
                metrics.drawdown,
                behavior_decision.similarity,
            )
            return record
        except Exception as exc:
            self.storage.mark_status(alpha_id, "failed")
            reward = self.scorer.score(SimulationMetrics(), failed=True)
            record = SimulationRecord(candidate=candidate, handle=None, metrics=SimulationMetrics(), reward=reward, api_status="failed", error=str(exc), completed_at=datetime.now(timezone.utc))
            self.storage.save_result(alpha_id, record, is_best=False)
            self.storage.append_failure(candidate, str(exc))
            LOGGER.exception("Simulation failed for candidate %s", candidate.expression)
            return record

    def _wait_for_completion(self, simulation_id: str) -> Dict[str, object]:
        for _ in range(self.settings.max_poll_attempts):
            payload = self.client.poll(simulation_id)
            status = str(payload.get("status", "unknown")).lower()
            if status in {"complete", "completed", "done"}:
                return payload
            if status in {"failed", "error", "cancelled"}:
                raise RuntimeError(f"Simulation failed with status: {status}")
            time.sleep(self.settings.poll_interval_seconds)
        raise TimeoutError(f"Simulation {simulation_id} timed out")

    def _load_seed_candidates(self) -> List[AlphaCandidate]:
        seed_rows = self.storage.list_seed_candidates(self.settings.seed_history_limit)
        candidates: List[AlphaCandidate] = []
        for row in seed_rows:
            params = json.loads(row["params_json"])
            wrappers = json.loads(row["wrappers_json"])
            params["wrappers"] = wrappers
            try:
                candidates.append(self.template_engine.instantiate(row["template_type"], params))
            except Exception:
                LOGGER.debug("Skipping seed candidate that could not be reconstructed: %s", row["expression"])
        return candidates

    def _build_generation_constraints(self) -> Dict[str, object]:
        rows = self.storage.summarize_template_performance()
        template_names = list(self.template_engine.templates.keys())
        prior_weights = self._checkpoint_overrides.get("template_weights", {})
        prior_active = self._checkpoint_overrides.get("active_templates", template_names)
        if not rows:
            return {
                "template_types": [name for name in prior_active if name in template_names] or template_names,
                "template_weights": {name: float(prior_weights.get(name, 1.0)) for name in template_names},
            }
        failure_summary = self._build_failure_summary()
        weights: Dict[str, float] = {}
        auto_blacklist: List[str] = []
        auto_whitelist: List[str] = []
        for row in rows:
            reward = float(row["avg_reward"] or 0.0)
            total_runs = float(row["total_runs"] or 0.0)
            failed_runs = float(row["failed_runs"] or 0.0)
            completed_runs = float(row["completed_runs"] or 0.0)
            avg_sharpe = float(row["avg_sharpe"] or 0.0)
            avg_fitness = float(row["avg_fitness"] or 0.0)
            failure_ratio = failed_runs / total_runs if total_runs else 0.0
            penalty = 1.0 - min(failure_ratio, 0.8)
            template_failure_penalty = 1.0 - min(failure_summary.get(row["template_type"], 0.0), 0.5)
            template_name = row["template_type"]
            base_weight = float(prior_weights.get(template_name, 1.0))
            weights[template_name] = max(base_weight * (1.0 + reward) * penalty * template_failure_penalty, 0.1)
            if total_runs >= 3 and (failure_ratio >= 0.75 or (completed_runs >= 3 and reward < -0.2 and avg_sharpe < 0 and avg_fitness < 0)):
                auto_blacklist.append(template_name)
            elif total_runs >= 3 and reward > 0.35 and avg_sharpe > 0.5 and avg_fitness > 0.5:
                auto_whitelist.append(template_name)
        active_templates = [
            name for name in template_names
            if name not in auto_blacklist
        ]
        if auto_whitelist:
            active_templates = sorted(set(active_templates) | set(auto_whitelist))
        if not active_templates:
            active_templates = template_names
        return {
            "template_weights": {name: weights.get(name, 1.0) for name in active_templates},
            "template_types": active_templates,
            "auto_blacklist": sorted(set(auto_blacklist)),
            "auto_whitelist": sorted(set(auto_whitelist)),
        }

    def _build_failure_summary(self) -> Dict[str, float]:
        rows = self.storage.summarize_failure_reasons()
        summary: Dict[str, float] = {}
        for row in rows:
            reason = str(row["error"] or "").lower()
            severity = 0.0
            if "filtered" in reason or "identity-subtraction" in reason:
                severity = 0.4
            elif "timeout" in reason:
                severity = 0.2
            elif "error" in reason or "failed" in reason:
                severity = 0.3
            summary[row["template_type"]] = max(summary.get(row["template_type"], 0.0), severity)
        return summary

    def _bootstrap_behavior_profiles(self) -> None:
        for row in self.storage.list_completed_behavior_profiles():
            try:
                metrics = SimulationMetrics(
                    sharpe=float(row["sharpe"] or 0.0),
                    fitness=float(row["fitness"] or 0.0),
                    returns=float(row["returns"] or 0.0),
                    drawdown=float(row["drawdown"] or 0.0),
                    turnover=float(row["turnover"] or 0.0),
                    margin=float(row["margin"] or 0.0),
                    extras=json.loads(row["extras_json"] or "{}"),
                )
                self.dedupe.register_existing_behavior(
                    fingerprint=row["fingerprint"],
                    normalized_expression=row["normalized_expression"],
                    template_type=row["template_type"],
                    metrics=metrics,
                )
            except Exception:
                LOGGER.debug("Skipping behavior bootstrap row for fingerprint=%s", row["fingerprint"])

    @staticmethod
    def _summarize_cycle(records: List[SimulationRecord]) -> Dict[str, float]:
        completed = [record for record in records if record.api_status in {"complete", "completed", "done"}]
        best = [record for record in completed if record.metrics.sharpe > 1.25 and record.metrics.fitness > 1.0]
        avg_reward = sum(record.reward.value for record in records) / max(len(records), 1)
        return {
            "submitted": float(len(records)),
            "completed": float(len(completed)),
            "best": float(len(best)),
            "avg_reward": avg_reward,
        }
