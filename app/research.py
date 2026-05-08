from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import csv
import json

from app.models import utc_now_iso

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
]

FAILED_FIELDS = PASSED_FIELDS + ["dominant_bottleneck", "error_type", "error"]


def initialize_research_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "experiment_decisions.jsonl").touch(exist_ok=True)
    (path / "failure_taxonomy.json").write_text(json.dumps(FAILURE_TAXONOMY, indent=2), encoding="utf-8")
    if not (path / "family_memory.json").exists():
        (path / "family_memory.json").write_text(
            json.dumps({"families": {}, "global_best": None, "lessons": [], "updated_at": utc_now_iso()}, indent=2),
            encoding="utf-8",
        )


def record_research_artifacts(research_dir: Path, results: Iterable[Dict[str, Any]], errors: Iterable[Dict[str, Any]]) -> None:
    initialize_research_dir(research_dir)
    result_rows = list(results)
    error_rows = list(errors)
    if not result_rows and not error_rows:
        return

    memory = _load_memory(research_dir / "family_memory.json")
    decisions: List[Dict[str, Any]] = []
    passed_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []

    for result in result_rows:
        decision = _decision_from_result(result, memory)
        decisions.append(decision)
        _update_memory(memory, result, decision)
        flat = _flat_result_row(result, decision)
        if decision["decision"] in {"validate_best_candidate", "promote_candidate"}:
            passed_rows.append(flat)
        else:
            failed_rows.append({**flat, "dominant_bottleneck": decision["dominant_bottleneck"], "error_type": "", "error": ""})

    for error in error_rows:
        decision = _decision_from_error(error)
        decisions.append(decision)
        _update_error_memory(memory, error, decision)
        failed_rows.append(_flat_error_row(error, decision))

    _write_jsonl(research_dir / "experiment_decisions.jsonl", decisions)
    _append_csv(research_dir / "passed_alphas.csv", PASSED_FIELDS, passed_rows)
    _append_csv(research_dir / "failed_alphas.csv", FAILED_FIELDS, failed_rows)
    memory["updated_at"] = utc_now_iso()
    (research_dir / "family_memory.json").write_text(json.dumps(memory, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    _write_best_alphas(research_dir / "best_alphas.txt", memory)


def _load_memory(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"families": {}, "global_best": None, "updated_at": utc_now_iso()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("families", {})
    payload.setdefault("global_best", None)
    payload.setdefault("lessons", [])
    return payload


def _decision_from_result(result: Dict[str, Any], memory: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    family = str(result.get("family") or "manual")
    current_fitness = _float(metrics.get("fitness"))
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

    current_sharpe = _float(metrics.get("sharpe"))

    if checks_failed > 0:
        decision = "fix_validation_failure"
        next_action = {"type": "validate_checks", "checks": ["weight_concentration", "sub_universe_sharpe", "self_corr"], "reason": "BRAIN checks failed."}
    elif current_fitness is not None and current_fitness >= 1.0 and current_sharpe is not None and current_sharpe >= 1.25:
        decision = "validate_best_candidate"
        bottleneck = "validation_pending"
        next_action = {
            "type": "validate_checks",
            "checks": ["self_corr", "os_performance"],
            "reason": "Candidate passed platform hard checks and crossed Sharpe/Fitness submission gates; stop blind tuning.",
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


def _update_memory(memory: Dict[str, Any], result: Dict[str, Any], decision: Dict[str, Any]) -> None:
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
    lesson = _derive_lesson(result, decision, family.get("recent_candidates", []))
    if lesson:
        family["lessons"] = _append_unique_lesson(family.get("lessons", []), lesson)
        memory["lessons"] = _append_unique_lesson(memory.get("lessons", []), lesson)
    if improved:
        family["best_candidate"] = candidate_snapshot
    if _is_better_candidate(candidate_snapshot, memory.get("global_best")):
        memory["global_best"] = candidate_snapshot


def _update_error_memory(memory: Dict[str, Any], error: Dict[str, Any], decision: Dict[str, Any]) -> None:
    family_name = str(error.get("family") or "manual")
    family = memory["families"].setdefault(family_name, {"status": "exploration", "tested_variants": 0, "consecutive_no_improvement": 0, "failure_modes": {}, "best_candidate": None, "recent_candidates": []})
    family["tested_variants"] = int(family.get("tested_variants", 0)) + 1
    family["consecutive_no_improvement"] = int(family.get("consecutive_no_improvement", 0)) + 1
    family["failure_modes"] = _updated_failure_modes(family.get("failure_modes", {}), decision["dominant_bottleneck"])
    family["status"] = _family_status(decision, family)


def _family_status(decision: Dict[str, Any], family: Dict[str, Any]) -> str:
    if decision["decision"] == "validate_best_candidate":
        return "candidate_validation"
    if int(family.get("consecutive_no_improvement", 0)) >= 5:
        return "stopped"
    if family.get("best_candidate"):
        return "development"
    return "exploration"


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
        "decision": decision["decision"],
        "dominant_bottleneck": decision["dominant_bottleneck"],
        "recorded_at": utc_now_iso(),
    }


def _derive_lesson(result: Dict[str, Any], decision: Dict[str, Any], recent_candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    metadata = result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {}
    changed_dimension = str(metadata.get("changed_dimension") or "").strip()
    parent_id = str(metadata.get("parent_candidate_id") or "").strip()
    if not changed_dimension or not parent_id:
        return None
    parent = _find_recent_candidate(recent_candidates, parent_id)
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
        "dominant_bottleneck": decision["dominant_bottleneck"],
        "error_type": error.get("error_type"),
        "error": error.get("error"),
    }


def _append_csv(path: Path, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


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


def _is_mock_candidate(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    metrics = candidate.get("metrics", {})
    return _is_mock_metrics(metrics if isinstance(metrics, dict) else {})


def _is_mock_metrics(metrics: Dict[str, Any]) -> bool:
    raw = metrics.get("raw", {})
    return isinstance(raw, dict) and raw.get("mode") == "mock"


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
