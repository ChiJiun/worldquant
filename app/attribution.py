from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import csv
import json

HIGHER_IS_BETTER = ("sharpe", "fitness", "returns", "margin")
LOWER_IS_BETTER = ("turnover", "drawdown")
ATTRIBUTION_METRICS = HIGHER_IS_BETTER + LOWER_IS_BETTER
CORE_METRICS = {"fitness", "sharpe"}


def candidate_metadata(item: Any) -> Dict[str, Any]:
    """Return a candidate's metadata with one level of nesting flattened.

    `data/candidates.jsonl` rows that wrap `parent_candidate_id` / `changed_dimension` inside a
    `"metadata": {...}` object end up as ``result["metadata"]["metadata"]`` because the simulator keeps
    every unknown key under ``metadata``. Outer keys win when both levels define the same name.
    """
    if not isinstance(item, dict):
        return {}
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    flat: Dict[str, Any] = {}
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        flat.update(nested)
    flat.update({key: value for key, value in metadata.items() if key != "metadata"})
    return flat


def flat_metrics(item: Any) -> Dict[str, Optional[float]]:
    metrics = item.get("metrics") if isinstance(item, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    return {name: _float(metrics.get(name)) for name in ATTRIBUTION_METRICS}


def compare_metrics(current: Any, reference: Any) -> Dict[str, Any]:
    """Per-metric deltas of ``current`` versus ``reference`` (both snapshots/result rows with a ``metrics`` dict)."""
    cur = flat_metrics(current)
    ref = flat_metrics(reference)
    improved: List[str] = []
    worsened: List[str] = []
    unchanged: List[str] = []
    missing: List[str] = []
    deltas: Dict[str, Dict[str, Optional[float]]] = {}
    for name in ATTRIBUTION_METRICS:
        before = ref[name]
        after = cur[name]
        if before is None or after is None:
            missing.append(name)
            continue
        delta = after - before
        pct = (delta / abs(before)) if before else None
        deltas[name] = {
            "from": before,
            "to": after,
            "delta": round(delta, 6),
            "pct": round(pct, 4) if pct is not None else None,
        }
        if delta == 0:
            unchanged.append(name)
            continue
        better = delta > 0 if name in HIGHER_IS_BETTER else delta < 0
        (improved if better else worsened).append(name)
    return {
        "improved": improved,
        "worsened": worsened,
        "unchanged": unchanged,
        "missing": missing,
        "deltas": deltas,
        "verdict": verdict(improved, worsened),
    }


def verdict(improved: List[str], worsened: List[str]) -> str:
    if not improved and not worsened:
        return "unchanged"
    if improved and not worsened:
        return "net_improvement"
    if worsened and not improved:
        return "regression"
    core_improved = CORE_METRICS & set(improved)
    core_worsened = CORE_METRICS & set(worsened)
    if core_improved and not core_worsened:
        return "improvement_with_trade_off"
    if core_worsened and not core_improved:
        return "regression_with_trade_off"
    return "trade_off"


def find_candidate(
    memory: Dict[str, Any],
    candidate_id: str,
    decisions_path: Optional[Path] = None,
    csv_paths: Sequence[Path] = (),
) -> Optional[Dict[str, Any]]:
    """Locate the latest snapshot of ``candidate_id``.

    Search order: family memory (recent candidates, family bests, global best), then the decisions log,
    then the passed/failed alpha CSVs. The CSVs matter for alphas that were recorded manually with
    ``record-passed-alpha`` and therefore never went through the recorder.
    """
    if not candidate_id:
        return None
    families = memory.get("families", {}) if isinstance(memory, dict) else {}
    families = families if isinstance(families, dict) else {}
    for family in families.values():
        if not isinstance(family, dict):
            continue
        recent = [item for item in family.get("recent_candidates", []) if isinstance(item, dict)]
        for snapshot in reversed(recent):
            if snapshot.get("candidate_id") == candidate_id:
                return snapshot
    for family in families.values():
        best = family.get("best_candidate") if isinstance(family, dict) else None
        if isinstance(best, dict) and best.get("candidate_id") == candidate_id:
            return best
    global_best = memory.get("global_best") if isinstance(memory, dict) else None
    if isinstance(global_best, dict) and global_best.get("candidate_id") == candidate_id:
        return global_best
    if decisions_path is not None:
        found = find_in_decisions(decisions_path, candidate_id)
        if found is not None:
            return found
    for csv_path in csv_paths:
        found = find_in_alpha_csv(csv_path, candidate_id)
        if found is not None:
            return found
    return None


def find_in_alpha_csv(path: Path, candidate_id: str) -> Optional[Dict[str, Any]]:
    """Latest passed/failed_alphas.csv row for ``candidate_id`` rebuilt as a snapshot with flat metrics."""
    if not candidate_id or not path.exists():
        return None
    found: Optional[Dict[str, Any]] = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("candidate_id") or "").strip() != candidate_id:
                continue
            metrics = {name: _float(row.get(name)) for name in ATTRIBUTION_METRICS if row.get(name) not in (None, "")}
            found = {
                "candidate_id": candidate_id,
                "family": row.get("family"),
                "expression": row.get("expression"),
                "result_id": row.get("result_id"),
                "recorded_at": row.get("recorded_at"),
                "metrics": metrics,
                "source": str(path),
            }
    return found


def find_in_decisions(path: Path, candidate_id: str) -> Optional[Dict[str, Any]]:
    """Latest `experiment_decisions.jsonl` row for ``candidate_id`` that carries metrics."""
    if not candidate_id or not path.exists():
        return None
    found: Optional[Dict[str, Any]] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("candidate_id") == candidate_id and isinstance(row.get("metrics"), dict):
            found = row
    return found


def build_attribution(
    memory: Dict[str, Any],
    candidate_id: Optional[str] = None,
    *,
    decisions_path: Optional[Path] = None,
    csv_paths: Sequence[Path] = (),
) -> Dict[str, Any]:
    """Compare a candidate with its parent, its family best and the global best."""
    if candidate_id:
        candidate = find_candidate(memory, candidate_id, decisions_path, csv_paths)
    else:
        global_best = memory.get("global_best")
        candidate = global_best if isinstance(global_best, dict) else None
    if candidate is None:
        raise ValueError(f"Candidate not found in research memory: {candidate_id or '<global_best>'}")

    metadata = candidate_metadata(candidate)
    if not metadata and decisions_path is not None:
        decision_row = find_in_decisions(decisions_path, str(candidate.get("candidate_id") or ""))
        metadata = candidate_metadata(decision_row) if decision_row else {}
    parent_id = str(metadata.get("parent_candidate_id") or "").strip()
    parent = find_candidate(memory, parent_id, decisions_path, csv_paths) if parent_id else None

    family_name = str(candidate.get("family") or "manual")
    families = memory.get("families", {}) if isinstance(memory.get("families"), dict) else {}
    family = families.get(family_name, {}) if isinstance(families.get(family_name), dict) else {}
    family_best = family.get("best_candidate")
    global_best = memory.get("global_best")

    if parent is not None:
        vs_parent = compare_metrics(candidate, parent)
        vs_parent["reference_candidate_id"] = parent.get("candidate_id")
        if parent.get("source"):
            vs_parent["reference_source"] = parent.get("source")
    else:
        vs_parent = {"status": "parent_not_found" if parent_id else "no_parent_recorded"}

    report = {
        "candidate_id": candidate.get("candidate_id"),
        "family": family_name,
        "expression": candidate.get("expression"),
        "result_id": candidate.get("result_id"),
        "recorded_at": candidate.get("recorded_at"),
        "changed_dimension": str(metadata.get("changed_dimension") or ""),
        "parent_candidate_id": parent_id,
        "metrics": flat_metrics(candidate),
        "vs_parent": vs_parent,
        "vs_family_best": _compare_or_self(candidate, family_best, "family_best"),
        "vs_global_best": _compare_or_self(candidate, global_best, "global_best"),
    }
    report["verdict"] = str(vs_parent.get("verdict") or vs_parent.get("status"))
    report["next_action_hint"] = _hint(report["verdict"], report["changed_dimension"])
    return report


def _compare_or_self(candidate: Dict[str, Any], reference: Any, label: str) -> Dict[str, Any]:
    if not isinstance(reference, dict):
        return {"status": f"no_{label}"}
    if reference.get("candidate_id") == candidate.get("candidate_id"):
        return {"status": f"is_{label}"}
    comparison = compare_metrics(candidate, reference)
    comparison["reference_candidate_id"] = reference.get("candidate_id")
    return comparison


def _hint(verdict_label: str, changed_dimension: str) -> str:
    dim = changed_dimension or "the changed dimension"
    return {
        "net_improvement": f"Keep {dim}; continue one-dimensional tuning from this candidate.",
        "improvement_with_trade_off": f"{dim} improved the core metrics but cost something else; keep it only if the worsened metric is not the family's dominant bottleneck.",
        "trade_off": f"{dim} improved one core metric and worsened the other; judge it by the family's dominant bottleneck (fitness already prices turnover and returns) instead of reverting by default.",
        "regression_with_trade_off": f"{dim} hurt the core metrics; revert to the parent and try a different dimension.",
        "regression": f"Revert {dim}; every available metric got worse.",
        "unchanged": f"{dim} had no measurable effect; drop it and test a different dimension.",
        "no_parent_recorded": "Record parent_candidate_id and changed_dimension in data/candidates.jsonl so the next experiment can be attributed.",
        "parent_not_found": "Parent id is not in research memory, the decisions log, or the passed/failed alpha CSVs; only family/global comparisons are available.",
    }.get(verdict_label, "Review the metric deltas before the next experiment.")


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
