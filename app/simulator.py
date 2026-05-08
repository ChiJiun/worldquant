from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json
import shutil
import time

from app.api import BrainClient
from app.config import Settings
from app.models import AlphaCandidate, SimulationMetrics, utc_now_iso


TERMINAL_SUCCESS = {"complete", "completed", "done"}
TERMINAL_FAILURE = {"failed", "error", "cancelled"}


def read_candidates(path: Path) -> List[AlphaCandidate]:
    if not path.exists():
        raise FileNotFoundError(f"Candidate file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        rows = payload.get("candidates", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON candidate file must be a list or {'candidates': [...]}")
        return [_candidate_from_mapping(row) for row in rows]
    candidates: List[AlphaCandidate] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            candidates.append(_candidate_from_mapping(json.loads(stripped)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return candidates


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _candidate_from_mapping(row: Dict[str, Any]) -> AlphaCandidate:
    if not isinstance(row, dict):
        raise ValueError("Each candidate row must be an object")
    expression = str(row.get("expression") or row.get("regular") or "").strip()
    metadata = {key: value for key, value in row.items() if key not in {"expression", "regular", "candidate_id", "family"}}
    return AlphaCandidate(
        candidate_id=str(row.get("candidate_id") or ""),
        family=str(row.get("family") or "manual"),
        expression=expression,
        metadata=metadata,
    )


class SimulateRunner:
    def __init__(self, settings: Settings, client: BrainClient) -> None:
        self.settings = settings
        self.client = client
        self.settings.ensure_directories()

    def run(self, input_path: Path, *, limit: Optional[int] = None) -> Path:
        candidates = read_candidates(input_path)
        if limit is not None:
            candidates = candidates[:limit]
        if not candidates:
            raise ValueError(f"No candidates found in {input_path}")

        run_id = utc_now_iso().replace(":", "").replace("-", "").replace("Z", "")
        run_dir = self.settings.output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, run_dir / f"input{input_path.suffix or '.jsonl'}")

        results: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for candidate in candidates:
            try:
                result = self._run_one(candidate)
                results.append(result)
                write_jsonl(run_dir / "results.jsonl", [result])
                write_jsonl(self.settings.output_dir / "simulate_results.jsonl", [result])
            except Exception as exc:
                error = {
                    "recorded_at": utc_now_iso(),
                    "candidate_id": candidate.candidate_id,
                    "family": candidate.family,
                    "expression": candidate.expression,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
                errors.append(error)
                write_jsonl(run_dir / "errors.jsonl", [error])
                write_jsonl(self.settings.output_dir / "simulate_errors.jsonl", [error])

        summary = {
            "run_id": run_id,
            "input": str(input_path),
            "total": len(candidates),
            "succeeded": len(results),
            "failed": len(errors),
            "settings": self.settings.simulation_settings_payload(),
            "created_at": utc_now_iso(),
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return run_dir

    def _run_one(self, candidate: AlphaCandidate) -> Dict[str, Any]:
        handle = self.client.simulate(candidate)
        terminal = self._wait_for_completion(handle.simulation_id)
        result_id = str(terminal.get("alpha") or terminal.get("alpha_id") or handle.simulation_id)
        metrics = self.client.fetch_result(result_id)
        return {
            "recorded_at": utc_now_iso(),
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            "expression": candidate.expression,
            "simulation_id": handle.simulation_id,
            "result_id": result_id,
            "terminal_status": terminal,
            "metrics": metrics.as_dict(),
        }

    def _wait_for_completion(self, simulation_id: str) -> Dict[str, Any]:
        last_payload: Dict[str, Any] = {}
        for _ in range(self.settings.max_poll_attempts):
            payload = self.client.poll(simulation_id)
            last_payload = payload
            status = str(payload.get("status", "unknown")).lower()
            if status in TERMINAL_SUCCESS:
                return payload
            if status in TERMINAL_FAILURE:
                raise RuntimeError(f"Simulation failed with status={status} payload={payload}")
            time.sleep(self.settings.poll_interval_seconds)
        raise TimeoutError(f"Simulation {simulation_id} timed out after {self.settings.max_poll_attempts} polls. last_payload={last_payload}")


def render_metrics(metrics: SimulationMetrics) -> str:
    payload = metrics.as_dict()
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
