from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import copy
import csv
import json
import logging
import math
import os
import tempfile

from app.attribution import candidate_metadata, compare_metrics, find_candidate
from app.models import utc_now_iso
from app.research_paths import ResearchPaths, ensure_research_layout, existing_or_new, research_paths

LOGGER = logging.getLogger(__name__)

FAILURE_TAXONOMY = [
    "turnover_too_high",
    "returns_too_low",
    "sharpe_too_low",
    "drawdown_too_high",
    "weight_concentration",
    "sub_universe_fail",
    "self_corr_fail",
    "signal_amplitude_destroyed",
    "over_smoothing",
    "hard_filter_destroyed_returns",
    "direction_wrong",
    "operator_invalid",
    "unit_incompatible",
    "platform_timeout",
    "platform_auth_error",
    "platform_error",
    "validation_failed",
    "validation_pending",
    "no_dominant_bottleneck",
]


PASSED_FIELDS = [
    "recorded_at",
    "candidate_id",
    "family",
    "expression",
    "result_id",
    "sharpe",
    "fitness",
    "returns",
    "drawdown",
    "turnover",
    "decision",
    "source",
]

FAILED_FIELDS = PASSED_FIELDS + ["dominant_bottleneck", "error_type", "error"]

# ``source`` column of passed/failed_alphas.csv and ``experiment_decisions.jsonl``: where the metrics came from.
SOURCE_LIVE = "live"
SOURCE_MOCK = "mock"
SOURCES = (SOURCE_LIVE, SOURCE_MOCK)


def initialize_research_dir(path: Path) -> None:
    paths = ensure_research_layout(path)
    paths.experiment_decisions.touch(exist_ok=True)
    paths.failure_taxonomy.write_text(json.dumps(FAILURE_TAXONOMY, indent=2), encoding="utf-8")
    if not paths.family_memory.exists():
        legacy_memory = _existing_family_memory_path(path, paths.family_memory)
        if legacy_memory.exists():
            paths.family_memory.write_text(legacy_memory.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            paths.family_memory.write_text(
                json.dumps({"families": {}, "global_best": None, "lessons": [], "updated_at": utc_now_iso()}, indent=2),
                encoding="utf-8",
            )


def _existing_family_memory_path(research_dir: Path, preferred: Path) -> Path:
    return existing_or_new(preferred, research_dir / "family_memory.json", research_dir / "old" / "family_memory.json")


def record_research_artifacts(
    research_dir: Path,
    results: Iterable[Dict[str, Any]],
    errors: Iterable[Dict[str, Any]],
    *,
    source: Optional[str] = None,
) -> None:
    """Append simulate results/errors to the research logs and update family memory.

    ``source`` (``live`` or ``mock``, default ``live``) is written to every decision row and to the
    ``source`` column of ``passed_alphas.csv`` / ``failed_alphas.csv`` so mock rows can be told apart
    from real BRAIN results afterwards. A result whose metrics carry the mock marker (``raw.mode=mock``
    or an ``alpha_id`` starting with ``mock-``) is tagged ``mock`` whatever ``source`` says.
    """
    default_source = normalize_source(source)
    initialize_research_dir(research_dir)
    paths = research_paths(research_dir)
    result_rows = list(results)
    error_rows = list(errors)
    if not result_rows and not error_rows:
        return

    memory = _load_memory(_existing_family_memory_path(research_dir, paths.family_memory))
    decisions: List[Dict[str, Any]] = []
    passed_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []

    for result in result_rows:
        decision = _decision_from_result(result, memory, paths)
        decision["source"] = result_source(result, default_source)
        _update_memory(memory, result, decision, paths)
        decision["workflow_loop"] = memory["families"].get(str(result.get("family") or "manual"), {}).get("workflow_loop")
        decisions.append(decision)
        flat = _flat_result_row(result, decision)
        if decision["decision"] in {"validate_best_candidate", "promote_candidate"}:
            passed_rows.append(flat)
        else:
            failed_rows.append({**flat, "dominant_bottleneck": decision["dominant_bottleneck"], "error_type": "", "error": ""})

    for error in error_rows:
        decision = _decision_from_error(error)
        decision["source"] = default_source
        decisions.append(decision)
        _update_error_memory(memory, error, decision)
        failed_rows.append(_flat_error_row(error, decision))

    _write_jsonl(paths.experiment_decisions, decisions)
    _append_csv(paths.passed_alphas, PASSED_FIELDS, passed_rows)
    _append_csv(paths.failed_alphas, FAILED_FIELDS, failed_rows)
    memory["updated_at"] = utc_now_iso()
    paths.family_memory.write_text(json.dumps(memory, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    _write_best_alphas(paths.best_alphas, memory)


PASSED_DECISIONS = {"validate_best_candidate", "promote_candidate"}
PASSED_METRIC_FIELDS = ("sharpe", "fitness", "returns", "drawdown", "turnover")


def normalize_source(value: Any) -> str:
    """Validate a ``source`` tag; ``None``/empty means ``live``."""
    text = str(value or "").strip().lower()
    if not text:
        return SOURCE_LIVE
    if text not in SOURCES:
        raise ValueError(f"source must be one of {list(SOURCES)}, got {value!r}")
    return text


def result_source(result: Dict[str, Any], default: str = SOURCE_LIVE) -> str:
    """``mock`` when the result's metrics carry the mock marker, else ``default``."""
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    return SOURCE_MOCK if _is_mock_metrics(metrics) else default


def is_mock_source(value: Any) -> bool:
    """True for a CSV/decision ``source`` value that marks a mock row (missing/blank = legacy live row)."""
    return str(value or "").strip().lower() == SOURCE_MOCK


def record_passed_alpha(research_dir: Path, row: Dict[str, Any], *, allow_duplicate: bool = False) -> Dict[str, Any]:
    """Append one verified alpha to passed_alphas.csv without hand-editing the CSV.

    This is the supported replacement for ad hoc append scripts: the row is
    normalized to PASSED_FIELDS, recorded_at defaults to now, decision must be a
    pass-gate decision, and an existing result_id is rejected unless
    allow_duplicate is set.
    """
    paths = ensure_research_layout(research_dir)
    normalized = _normalize_passed_row(row)
    if not allow_duplicate and normalized["result_id"]:
        for existing in _read_csv_rows(paths.passed_alphas):
            if str(existing.get("result_id") or "").strip() == normalized["result_id"]:
                raise ValueError(
                    f"result_id {normalized['result_id']} already exists in {paths.passed_alphas}; "
                    "pass allow_duplicate=True to append anyway"
                )
    _append_csv(paths.passed_alphas, PASSED_FIELDS, [normalized])
    return normalized


def _normalize_passed_row(row: Dict[str, Any]) -> Dict[str, Any]:
    expression = str(row.get("expression") or "").strip()
    if not expression:
        raise ValueError("expression is required")
    candidate_id = str(row.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("candidate_id is required")
    result_id = str(row.get("result_id") or "").strip()
    if not result_id:
        raise ValueError("result_id is required: passed alphas are deduplicated by the BRAIN alpha id")
    decision = str(row.get("decision") or "validate_best_candidate").strip() or "validate_best_candidate"
    if decision not in PASSED_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(PASSED_DECISIONS)}, got {decision!r}")
    normalized: Dict[str, Any] = {
        "recorded_at": _normalize_recorded_at(row.get("recorded_at")),
        "candidate_id": candidate_id,
        "family": str(row.get("family") or "manual").strip() or "manual",
        "expression": expression,
        "result_id": result_id,
        "decision": decision,
        "source": SOURCE_LIVE,
    }
    for name in PASSED_METRIC_FIELDS:
        raw_value = row.get(name)
        value = _float(raw_value)
        if raw_value not in (None, "") and value is None:
            raise ValueError(f"{name} must be a number, got {raw_value!r}")
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number, got {raw_value!r}")
        normalized[name] = "" if value is None else value
    return normalized


def _normalize_recorded_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return utc_now_iso()
    probe = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(probe)
    except ValueError as exc:
        raise ValueError(f"recorded_at must be an ISO-8601 timestamp such as 2026-05-21T08:09:57Z, got {text!r}") from exc
    return text


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_family_memory(research_dir: Path) -> Dict[str, Any]:
    """Read family memory from the current layout, falling back to legacy locations."""
    return _load_memory(_existing_family_memory_path(research_dir, research_paths(research_dir).family_memory))


def save_family_memory(research_dir: Path, memory: Dict[str, Any]) -> Path:
    paths = ensure_research_layout(research_dir)
    memory["updated_at"] = utc_now_iso()
    paths.family_memory.write_text(json.dumps(memory, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return paths.family_memory


def update_candidate_metrics(
    memory: Dict[str, Any],
    candidate_id: str,
    metrics: Dict[str, Any],
    result_id: Optional[str] = None,
) -> int:
    """Replace the stored metrics of every snapshot of ``candidate_id`` (recent, family best, global best).

    ``candidate_id`` alone is not a safe key: the same id has been reused across families for different
    expressions, so when ``result_id`` (the BRAIN alpha id the metrics came from) is given only snapshots
    carrying that exact ``result_id`` are touched. Each snapshot gets its own copy of ``metrics``.
    """
    refreshed_at = utc_now_iso()
    updated = 0
    wanted_result = str(result_id or "").strip()

    def _apply(snapshot: Any) -> None:
        nonlocal updated
        if not isinstance(snapshot, dict) or snapshot.get("candidate_id") != candidate_id:
            return
        if wanted_result and str(snapshot.get("result_id") or "").strip() != wanted_result:
            return
        snapshot["metrics"] = copy.deepcopy(metrics)
        snapshot["refreshed_at"] = refreshed_at
        updated += 1

    families = memory.get("families", {}) if isinstance(memory.get("families"), dict) else {}
    for family in families.values():
        if not isinstance(family, dict):
            continue
        for snapshot in family.get("recent_candidates", []) or []:
            _apply(snapshot)
        _apply(family.get("best_candidate"))
    _apply(memory.get("global_best"))
    return updated


def _load_memory(path: Path) -> Dict[str, Any]:
    """Read family memory; a missing file is an empty memory, an unreadable one is an error.

    Returning an empty dict for a corrupt file used to make callers report "missing or empty" and
    let the next recorder run overwrite the damaged file; now the caller sees ``ValueError`` naming
    the file so the user can repair or restore it first.
    """
    if not path.exists():
        return {"families": {}, "global_best": None, "updated_at": utc_now_iso()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"family memory file is corrupt (invalid JSON) at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"family memory file is corrupt (expected a JSON object, got {type(payload).__name__}) at {path}")
    payload.setdefault("families", {})
    payload.setdefault("global_best", None)
    payload.setdefault("lessons", [])
    return payload


def _find_parent(memory: Dict[str, Any], parent_id: str, paths: Optional[ResearchPaths] = None) -> Optional[Dict[str, Any]]:
    """Parent lookup shared by the recorder and ``python -m app attribute``: memory, decisions log, then CSVs."""
    if not parent_id:
        return None
    if paths is None:
        return find_candidate(memory, parent_id)
    return find_candidate(memory, parent_id, paths.experiment_decisions, (paths.passed_alphas, paths.failed_alphas))


def _decision_from_result(result: Dict[str, Any], memory: Dict[str, Any], paths: Optional[ResearchPaths] = None) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    family = str(result.get("family") or "manual")
    current_fitness = _float(metrics.get("fitness"))
    current_sharpe = _float(metrics.get("sharpe"))
    current_turnover = _turnover_percent(metrics.get("turnover"))
    checks_failed = _checks_failed(metrics)
    best_fitness = _best_family_fitness(memory, family)
    best_candidate = memory.get("families", {}).get(family, {}).get("best_candidate")
    if _is_mock_candidate(best_candidate) and not _is_mock_metrics(metrics):
        best_fitness = None
    bottleneck = _dominant_bottleneck(metrics)
    improved = []
    worsened = []
    if current_fitness is not None and best_fitness is not None:
        if current_fitness > best_fitness:
            improved.append("fitness")
        elif current_fitness < best_fitness:
            worsened.append("fitness")
    metadata = candidate_metadata(result)
    parent_id = str(metadata.get("parent_candidate_id") or "").strip()
    parent = _find_parent(memory, parent_id, paths)
    if parent is not None:
        latest_vs_parent = compare_metrics(result, parent)
        latest_vs_parent["reference_candidate_id"] = parent.get("candidate_id")
        if parent.get("found_in"):
            latest_vs_parent["reference_found_in"] = parent.get("found_in")
    else:
        latest_vs_parent = {"status": "parent_not_found" if parent_id else "no_parent_recorded"}

    if checks_failed > 0:
        decision = "fix_validation_failure"
        next_action = {"type": "validate_checks", "checks": ["weight_concentration", "sub_universe_sharpe", "self_corr"], "reason": "BRAIN checks failed."}
    elif current_fitness is not None and current_fitness >= 1.0 and current_sharpe is not None and current_sharpe >= 1.25:
        decision = "validate_best_candidate"
        bottleneck = "validation_pending"
        next_action = {
            "type": "validate_checks",
            "checks": ["self_corr", "os_performance"],
            "reason": "Candidate passed platform hard checks and crossed the pass-alpha gate; stop blind tuning.",
        }
    elif current_fitness is not None and current_turnover is not None and current_fitness > 1.2 and current_turnover < 40:
        decision = "validate_best_candidate"
        bottleneck = "validation_pending"
        next_action = {
            "type": "validate_checks",
            "checks": ["weight_concentration", "sub_universe_sharpe", "self_corr", "os_performance"],
            "reason": "Candidate crossed Fitness > 1.2 and Turnover < 40; stop blind tuning.",
        }
    elif bottleneck != "no_dominant_bottleneck" and (current_fitness is None or current_fitness < 1.0):
        decision = "record_failure"
        next_action = {"type": "test_formula", "reason": f"Dominant bottleneck is {bottleneck}; change one design dimension only."}
    elif best_fitness is None or (current_fitness is not None and current_fitness > best_fitness):
        decision = "continue_family"
        next_action = {"type": "test_formula", "reason": "Candidate improved family best; continue one-dimensional tuning."}
    else:
        decision = "record_failure"
        next_action = {"type": "test_formula", "reason": f"Dominant bottleneck is {bottleneck}; change one design dimension only."}

    return {
        "recorded_at": utc_now_iso(),
        "candidate_id": result.get("candidate_id"),
        "family": family,
        "expression": result.get("expression"),
        "result_id": result.get("result_id"),
        "decision": decision,
        "dominant_bottleneck": bottleneck,
        "latest_vs_family_best": {"improved": improved, "worsened": worsened},
        "parent_candidate_id": parent_id,
        "changed_dimension": str(metadata.get("changed_dimension") or ""),
        "latest_vs_parent": latest_vs_parent,
        "causal_interpretation": _causal_interpretation(bottleneck),
        "next_action": next_action,
        "metrics": metrics,
        "metadata": result.get("metadata", {}),
    }


def _decision_from_error(error: Dict[str, Any]) -> Dict[str, Any]:
    bottleneck = _error_bottleneck(str(error.get("error_type") or ""), str(error.get("error") or ""))
    return {
        "recorded_at": utc_now_iso(),
        "candidate_id": error.get("candidate_id"),
        "family": error.get("family") or "manual",
        "expression": error.get("expression"),
        "result_id": None,
        "decision": "record_failure",
        "dominant_bottleneck": bottleneck,
        "latest_vs_family_best": {"improved": [], "worsened": []},
        "causal_interpretation": _causal_interpretation(bottleneck),
        "next_action": {"type": "test_formula", "reason": f"Fix {bottleneck} before retrying."},
        "error_type": error.get("error_type"),
        "error": error.get("error"),
    }


def _update_memory(
    memory: Dict[str, Any],
    result: Dict[str, Any],
    decision: Dict[str, Any],
    paths: Optional[ResearchPaths] = None,
) -> None:
    family_name = str(result.get("family") or "manual")
    family = memory["families"].setdefault(
        family_name,
        {
            "status": "exploration",
            "tested_variants": 0,
            "consecutive_no_improvement": 0,
            "failure_modes": {},
            "best_candidate": None,
            "recent_candidates": [],
        },
    )
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    current_fitness = _float(metrics.get("fitness"))
    best_fitness = _fitness_from_candidate(family.get("best_candidate"))
    if _is_mock_candidate(family.get("best_candidate")) and not _is_mock_metrics(metrics):
        best_fitness = None
    improved = best_fitness is None or (current_fitness is not None and current_fitness > best_fitness)

    family["tested_variants"] = int(family.get("tested_variants", 0)) + 1
    family["consecutive_no_improvement"] = 0 if improved else int(family.get("consecutive_no_improvement", 0)) + 1
    family["failure_modes"] = _updated_failure_modes(family.get("failure_modes", {}), decision["dominant_bottleneck"])
    family["status"] = _family_status(decision, family)
    candidate_snapshot = _candidate_snapshot(result, decision)
    family["recent_candidates"] = (family.get("recent_candidates", []) + [candidate_snapshot])[-20:]
    lesson = _derive_lesson(result, decision, family.get("recent_candidates", []), memory, paths)
    if lesson:
        family["lessons"] = _append_unique_lesson(family.get("lessons", []), lesson)
        memory["lessons"] = _append_unique_lesson(memory.get("lessons", []), lesson)
    if improved:
        family["best_candidate"] = candidate_snapshot
    if _is_better_candidate(candidate_snapshot, memory.get("global_best")):
        memory["global_best"] = candidate_snapshot
    family["workflow_loop"] = _workflow_loop(family)


def _update_error_memory(memory: Dict[str, Any], error: Dict[str, Any], decision: Dict[str, Any]) -> None:
    family_name = str(error.get("family") or "manual")
    family = memory["families"].setdefault(family_name, {"status": "exploration", "tested_variants": 0, "consecutive_no_improvement": 0, "failure_modes": {}, "best_candidate": None, "recent_candidates": []})
    family["tested_variants"] = int(family.get("tested_variants", 0)) + 1
    family["consecutive_no_improvement"] = int(family.get("consecutive_no_improvement", 0)) + 1
    family["failure_modes"] = _updated_failure_modes(family.get("failure_modes", {}), decision["dominant_bottleneck"])
    family["status"] = _family_status(decision, family)
    family["workflow_loop"] = _workflow_loop(family)


def _family_status(decision: Dict[str, Any], family: Dict[str, Any]) -> str:
    if decision["decision"] == "validate_best_candidate":
        return "candidate_validation"
    if family.get("workflow_loop") in {"pass_alpha_improvement_loop", "improve_pass_alpha_loop"}:
        return "pass_alpha_improvement"
    if int(family.get("consecutive_no_improvement", 0)) >= 5:
        return "stopped"
    if family.get("best_candidate"):
        return "development"
    return "exploration"


def _workflow_loop(family: Dict[str, Any]) -> str:
    if _is_pass_alpha_candidate(family.get("best_candidate")):
        return "pass_alpha_improvement_loop"
    return "pass_alpha_search_loop"


def summarize_workflow_state(research_dir: Path, requested_mode: str = "auto") -> Dict[str, Any]:
    paths = research_paths(research_dir)
    memory = _load_memory(_existing_family_memory_path(research_dir, paths.family_memory))
    families = memory.get("families", {}) if isinstance(memory.get("families"), dict) else {}
    active_family_name, active_family = _select_active_family(memory)
    active_loop = _workflow_loop(active_family) if active_family else "pass_alpha_search_loop"
    if requested_mode == "pass-alpha-search":
        requested_loop = "pass_alpha_search_loop"
    elif requested_mode == "pass-alpha-improvement":
        requested_loop = "pass_alpha_improvement_loop"
    else:
        requested_loop = active_loop
    best_candidate = memory.get("global_best")
    return {
        "requested_mode": requested_mode,
        "active_mode": requested_loop,
        "active_loop": active_loop,
        "active_family": active_family_name,
        "family_status": active_family.get("status") if isinstance(active_family, dict) else None,
        "global_best_candidate": best_candidate.get("candidate_id") if isinstance(best_candidate, dict) else None,
        "best_family_candidate": active_family.get("best_candidate", {}).get("candidate_id") if isinstance(active_family, dict) and isinstance(active_family.get("best_candidate"), dict) else None,
        "suggested_next_action": _research_next_action(requested_loop, active_loop, active_family),
        "family_count": len(families),
    }


def _select_active_family(memory: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    families = memory.get("families", {})
    if not isinstance(families, dict) or not families:
        return "manual", {}
    global_best = memory.get("global_best")
    if isinstance(global_best, dict):
        family_name = str(global_best.get("family") or "manual")
        family = families.get(family_name)
        if isinstance(family, dict):
            return family_name, family
    for family_name, family in families.items():
        if isinstance(family, dict) and family.get("best_candidate"):
            return str(family_name), family
    family_name, family = next(iter(families.items()))
    return str(family_name), family if isinstance(family, dict) else {}


def _research_next_action(requested_loop: str, active_loop: str, family: Dict[str, Any]) -> Dict[str, Any]:
    if requested_loop == "pass_alpha_improvement_loop" or active_loop == "pass_alpha_improvement_loop":
        if isinstance(family.get("best_candidate"), dict):
            return {
                "type": "validate_checks" if _is_pass_alpha_candidate(family.get("best_candidate")) else "test_formula",
                "reason": "Improve the current pass-worthy family on one design dimension at a time.",
            }
        return {"type": "test_formula", "reason": "No pass-worthy family found yet; continue search or switch families."}
    return {"type": "test_formula", "reason": "Search for a new family or a new one-change candidate."}


def _dominant_bottleneck(metrics: Dict[str, Any]) -> str:
    if _checks_failed(metrics) > 0:
        return "validation_failed"
    turnover = _turnover_percent(metrics.get("turnover"))
    returns = _float(metrics.get("returns"))
    sharpe = _float(metrics.get("sharpe"))
    drawdown = _float(metrics.get("drawdown"))
    fitness = _float(metrics.get("fitness"))
    if turnover is not None and turnover > 40:
        return "turnover_too_high"
    if drawdown is not None and drawdown > 0.2:
        return "drawdown_too_high"
    if returns is not None and returns < 0.05:
        return "returns_too_low"
    if sharpe is not None and sharpe < 1.0:
        return "sharpe_too_low"
    if fitness is not None and fitness < 1.0:
        return "returns_too_low"
    return "no_dominant_bottleneck"


def _error_bottleneck(error_type: str, error: str) -> str:
    text = f"{error_type} {error}".lower()
    if "timeout" in text:
        return "platform_timeout"
    if "auth" in text or "401" in text or "403" in text:
        return "platform_auth_error"
    if "operator" in text or "unit" in text:
        return "operator_invalid"
    return "platform_error"


def _causal_interpretation(bottleneck: str) -> str:
    return {
        "turnover_too_high": "Signal may be too reactive; test smoothing or slower horizon as a single change.",
        "returns_too_low": "The proxy may remove too much edge or the mechanism may be weak in this universe.",
        "sharpe_too_low": "Returns are not stable enough relative to risk; inspect horizon and normalization.",
        "drawdown_too_high": "Tail exposure may be too close to raw signal amplitude.",
        "validation_failed": "Candidate needs concentration, sub-universe, or self-correlation validation before tuning.",
        "platform_timeout": "External simulation did not return a stable result.",
        "platform_auth_error": "External API authentication failed.",
        "operator_invalid": "Expression likely used an unsupported operator or incompatible unit.",
        "validation_pending": "Metrics are promising enough to stop blind tuning and run validation checks.",
        "no_dominant_bottleneck": "No dominant bottleneck detected from available metrics.",
    }.get(bottleneck, "Record the failure mode before proposing the next one-dimensional experiment.")


def _updated_failure_modes(current: Dict[str, Any], bottleneck: str) -> Dict[str, int]:
    if bottleneck in {"validation_pending", "no_dominant_bottleneck"}:
        return {key: int(value) for key, value in current.items()}
    return dict(Counter(current) + Counter([bottleneck]))


def _candidate_snapshot(result: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "candidate_id": result.get("candidate_id"),
        "family": result.get("family"),
        "expression": result.get("expression"),
        "result_id": result.get("result_id"),
        "metrics": result.get("metrics", {}),
        "metadata": candidate_metadata(result),
        "decision": decision["decision"],
        "dominant_bottleneck": decision["dominant_bottleneck"],
        "recorded_at": utc_now_iso(),
    }


def _derive_lesson(
    result: Dict[str, Any],
    decision: Dict[str, Any],
    recent_candidates: List[Dict[str, Any]],
    memory: Optional[Dict[str, Any]] = None,
    paths: Optional[ResearchPaths] = None,
) -> Optional[Dict[str, Any]]:
    metadata = candidate_metadata(result)
    changed_dimension = str(metadata.get("changed_dimension") or "").strip()
    parent_id = str(metadata.get("parent_candidate_id") or "").strip()
    if not changed_dimension or not parent_id:
        return None
    parent = _find_recent_candidate(recent_candidates, parent_id)
    if not parent and memory is not None:
        parent = _find_parent(memory, parent_id, paths)
    if not parent:
        return None
    current_metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    parent_metrics = parent.get("metrics", {}) if isinstance(parent.get("metrics"), dict) else {}
    improved = _metric_changes(parent_metrics, current_metrics, better="higher", names=["sharpe", "fitness", "returns", "margin"])
    improved += _metric_changes(parent_metrics, current_metrics, better="lower", names=["turnover", "drawdown"])
    worsened = _metric_changes(parent_metrics, current_metrics, better="lower", names=["sharpe", "fitness", "returns", "margin"])
    worsened += _metric_changes(parent_metrics, current_metrics, better="higher", names=["turnover", "drawdown"])
    if not improved and not worsened:
        return None
    summary = f"{changed_dimension}: improved {', '.join(improved) or 'none'}; worsened {', '.join(worsened) or 'none'}."
    return {
        "learned_at": utc_now_iso(),
        "family": result.get("family"),
        "candidate_id": result.get("candidate_id"),
        "parent_candidate_id": parent_id,
        "changed_dimension": changed_dimension,
        "dominant_bottleneck": decision.get("dominant_bottleneck"),
        "summary": summary,
        "next_use": _lesson_next_use(decision.get("dominant_bottleneck"), improved, worsened),
    }


def _find_recent_candidate(candidates: List[Dict[str, Any]], candidate_id: str) -> Optional[Dict[str, Any]]:
    for candidate in reversed(candidates):
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id:
            return candidate
    return None


def _metric_changes(parent: Dict[str, Any], current: Dict[str, Any], *, better: str, names: List[str]) -> List[str]:
    changes: List[str] = []
    for name in names:
        before = _float(parent.get(name))
        after = _float(current.get(name))
        if before is None or after is None or before == after:
            continue
        is_improved = after > before if better == "higher" else after < before
        if is_improved:
            changes.append(f"{name} {before:g}->{after:g}")
    return changes


def _lesson_next_use(bottleneck: Any, improved: List[str], worsened: List[str]) -> str:
    if bottleneck == "validation_failed":
        return "Keep useful one-change improvements, but do not promote until failed platform checks clear."
    if improved and not worsened:
        return "Prefer this design direction for the next one-change experiment in the same family."
    if worsened and not improved:
        return "Avoid repeating this design change unless a new bottleneck explicitly calls for it."
    return "Treat as a trade-off and compare against the active bottleneck before continuing."


def _append_unique_lesson(existing: Any, lesson: Dict[str, Any]) -> List[Dict[str, Any]]:
    lessons = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    key = (lesson.get("family"), lesson.get("candidate_id"), lesson.get("changed_dimension"), lesson.get("summary"))
    for item in lessons:
        item_key = (item.get("family"), item.get("candidate_id"), item.get("changed_dimension"), item.get("summary"))
        if item_key == key:
            return lessons[-50:]
    return (lessons + [lesson])[-50:]


def _flat_result_row(result: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    return {
        "recorded_at": result.get("recorded_at") or utc_now_iso(),
        "candidate_id": result.get("candidate_id"),
        "family": result.get("family"),
        "expression": result.get("expression"),
        "result_id": result.get("result_id"),
        "sharpe": metrics.get("sharpe"),
        "fitness": metrics.get("fitness"),
        "returns": metrics.get("returns"),
        "drawdown": metrics.get("drawdown"),
        "turnover": metrics.get("turnover"),
        "decision": decision["decision"],
        "source": decision.get("source") or SOURCE_LIVE,
    }


def _flat_error_row(error: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "recorded_at": error.get("recorded_at") or utc_now_iso(),
        "candidate_id": error.get("candidate_id"),
        "family": error.get("family"),
        "expression": error.get("expression"),
        "result_id": "",
        "sharpe": "",
        "fitness": "",
        "returns": "",
        "drawdown": "",
        "turnover": "",
        "decision": decision["decision"],
        "source": decision.get("source") or SOURCE_LIVE,
        "dominant_bottleneck": decision["dominant_bottleneck"],
        "error_type": error.get("error_type"),
        "error": error.get("error"),
    }


def _append_csv(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    """Append ``rows`` to a CSV whose header is ``fields``.

    A CSV written before a column existed (for example ``source``) is rewritten once with the new
    header so the appended rows do not overflow the old one; existing rows get an empty value in the
    new column. A header with columns this code does not know is left alone and appending follows it;
    the values of ``fields`` missing from that header are dropped, and a warning names them because
    a dropped ``source`` means ``select-alphas`` can no longer tell those rows apart from live ones.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    header = _csv_header(path)
    if header is None:
        fieldnames = fields
    elif header == fields:
        fieldnames = fields
    elif set(header) <= set(fields):
        _rewrite_csv_with_fields(path, fields)
        fieldnames = fields
    else:
        fieldnames = header
        unknown = [name for name in header if name not in fields]
        dropped = [name for name in fields if name not in header]
        LOGGER.warning(
            "CSV %s has a header this version does not know (unknown columns: %s); appending with that "
            "header and dropping %s from the new rows",
            path,
            ", ".join(repr(name) for name in unknown),
            ", ".join(repr(name) for name in dropped) or "nothing",
        )
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        if header is None:
            writer.writeheader()
        writer.writerows(rows)


def _csv_header(path: Path) -> Optional[List[str]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle), None)


def _rewrite_csv_with_fields(path: Path, fields: List[str]) -> None:
    """Rewrite ``path`` with header ``fields``, keeping every existing row.

    The new file is written next to ``path`` and swapped in with ``os.replace`` so an interrupted
    rewrite leaves the original log untouched instead of half-written.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        existing = list(csv.DictReader(handle))
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(existing)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_best_alphas(path: Path, memory: Dict[str, Any]) -> None:
    lines = []
    global_best = memory.get("global_best")
    if global_best:
        lines.append("GLOBAL BEST")
        lines.append(_format_best(global_best))
        lines.append("")
    for family_name, family in sorted(memory.get("families", {}).items()):
        best = family.get("best_candidate")
        if not best:
            continue
        lines.append(f"FAMILY {family_name}")
        lines.append(_format_best(best))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + ("\n" if lines else ""), encoding="utf-8")


def _format_best(candidate: Dict[str, Any]) -> str:
    metrics = candidate.get("metrics", {})
    return (
        f"{candidate.get('candidate_id')} fitness={metrics.get('fitness')} sharpe={metrics.get('sharpe')} "
        f"turnover={metrics.get('turnover')} returns={metrics.get('returns')} expression={candidate.get('expression')}"
    )


def _best_family_fitness(memory: Dict[str, Any], family: str) -> Optional[float]:
    return _fitness_from_candidate(memory.get("families", {}).get(family, {}).get("best_candidate"))


def _fitness_from_candidate(candidate: Any) -> Optional[float]:
    if not isinstance(candidate, dict):
        return None
    return _float(candidate.get("metrics", {}).get("fitness"))


def _is_better_candidate(candidate: Dict[str, Any], current_best: Any) -> bool:
    if _is_mock_candidate(current_best) and not _is_mock_candidate(candidate):
        return True
    if _is_mock_candidate(candidate) and not _is_mock_candidate(current_best):
        return False
    candidate_fitness = _fitness_from_candidate(candidate)
    best_fitness = _fitness_from_candidate(current_best)
    return candidate_fitness is not None and (best_fitness is None or candidate_fitness > best_fitness)


def _is_pass_alpha_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    return str(candidate.get("decision") or "") in {"validate_best_candidate", "promote_candidate"}


def _is_mock_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    metrics = candidate.get("metrics", {})
    return _is_mock_metrics(metrics if isinstance(metrics, dict) else {})


def _is_mock_metrics(metrics: Dict[str, Any]) -> bool:
    """``MockBrainClient`` marks its metrics with ``raw.mode=mock`` and ``alpha_id=mock-<id>``."""
    raw = metrics.get("raw", {})
    if isinstance(raw, dict) and raw.get("mode") == "mock":
        return True
    return str(metrics.get("alpha_id") or "").startswith("mock-")


def _checks_failed(metrics: Dict[str, Any]) -> int:
    explicit = _float(metrics.get("checks_failed"))
    if explicit is not None and explicit > 0:
        return int(explicit)
    raw = metrics.get("raw", {})
    if not isinstance(raw, dict):
        return int(explicit or 0)
    is_payload = raw.get("is", {}) if isinstance(raw.get("is"), dict) else {}
    checks = raw.get("checks") or is_payload.get("checks") or []
    if not isinstance(checks, list):
        return int(explicit or 0)
    return len([
        check for check in checks
        if isinstance(check, dict) and str(check.get("result") or "").upper() == "FAIL"
    ])


def _turnover_percent(value: Any) -> Optional[float]:
    numeric = _float(value)
    if numeric is None:
        return None
    return numeric * 100 if numeric <= 1 else numeric


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
