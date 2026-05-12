from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import csv
import json

from app.models import utc_now_iso
from app.research_paths import ensure_research_layout, existing_or_new


VALIDATION_CHECKS = [
    "weight_concentration",
    "sub_universe_sharpe",
    "self_corr",
    "os_performance",
]


CSV_FIELDS = [
    "recorded_at",
    "candidate_id",
    "family",
    "result_id",
    "decision",
    "overall_status",
    "blocking_checks",
]


def validate_candidate_from_memory(research_dir: Path, candidate_id: Optional[str] = None, *, persist: bool = False) -> Dict[str, Any]:
    paths = ensure_research_layout(research_dir)
    memory = _load_json(existing_or_new(paths.family_memory, research_dir / "family_memory.json", research_dir / "old" / "family_memory.json"))
    candidate = _select_candidate(memory, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate not found in family_memory.json: {candidate_id or '<global_best>'}")

    report = _build_report(candidate)
    if persist:
        _append_jsonl(paths.validation_reports_jsonl, [report])
        _append_csv(paths.validation_reports_csv, [_flat_report(report)])
    return report


def _build_report(candidate: Dict[str, Any]) -> Dict[str, Any]:
    metrics = candidate.get("metrics", {}) if isinstance(candidate.get("metrics"), dict) else {}
    raw = metrics.get("raw", {}) if isinstance(metrics.get("raw"), dict) else {}
    platform_checks = _platform_checks(raw)
    failed_platform_checks = [
        check for check in platform_checks
        if str(check.get("result") or "").upper() == "FAIL"
    ]

    checks = {
        "weight_concentration": _check_from_platform(platform_checks, ["weight", "concentration"]),
        "sub_universe_sharpe": _check_from_platform(platform_checks, ["sub", "universe"]),
        "self_corr": _check_from_platform(platform_checks, ["self", "corr"]),
        "os_performance": _check_from_platform(platform_checks, ["os", "out", "sample"]),
    }

    if not platform_checks:
        for name in VALIDATION_CHECKS:
            checks[name] = {
                "status": "needs_live_result",
                "reason": "No platform validation checks were available in the stored result raw payload.",
            }

    blocking = [
        name for name, check in checks.items()
        if check["status"] in {"fail", "needs_live_result", "missing", "pending"}
    ]
    decision = "promote_template" if not blocking else "validation_incomplete"

    return {
        "recorded_at": utc_now_iso(),
        "candidate_id": candidate.get("candidate_id"),
        "family": candidate.get("family"),
        "expression": candidate.get("expression"),
        "result_id": candidate.get("result_id"),
        "decision": decision,
        "overall_status": "pass" if not blocking else "blocked",
        "blocking_checks": blocking,
        "checks": checks,
        "metrics": metrics,
        "platform_failed_checks": failed_platform_checks,
        "next_action": _next_action(blocking),
    }


def _next_action(blocking: List[str]) -> Dict[str, Any]:
    if not blocking:
        return {"type": "promote_template", "reason": "All available validation checks passed."}
    if all(check in VALIDATION_CHECKS for check in blocking):
        return {
            "type": "validate_checks",
            "reason": "Validation requires live BRAIN result checks before more formula tuning.",
            "checks": blocking,
        }
    return {"type": "record_failure", "reason": "Validation produced blocking failures."}


def _platform_checks(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    is_payload = raw.get("is", {}) if isinstance(raw.get("is"), dict) else {}
    checks = raw.get("checks") or is_payload.get("checks") or []
    return [check for check in checks if isinstance(check, dict)] if isinstance(checks, list) else []


def _check_from_platform(platform_checks: List[Dict[str, Any]], name_parts: List[str]) -> Dict[str, str]:
    matched = []
    for check in platform_checks:
        label = " ".join(str(check.get(key) or "") for key in ("name", "description", "limit", "result")).lower()
        if any(part in label for part in name_parts):
            matched.append(check)
    if not matched:
        return {"status": "missing", "reason": "No matching platform check found in raw result."}
    failed = [check for check in matched if str(check.get("result") or "").upper() == "FAIL"]
    if failed:
        return {"status": "fail", "reason": json.dumps(failed, ensure_ascii=False)}
    pending = [check for check in matched if str(check.get("result") or "").upper() == "PENDING"]
    if pending:
        return {"status": "pending", "reason": json.dumps(pending, ensure_ascii=False)}
    return {"status": "pass", "reason": json.dumps(matched, ensure_ascii=False)}


def _select_candidate(memory: Dict[str, Any], candidate_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not candidate_id:
        best = memory.get("global_best")
        return best if isinstance(best, dict) else None
    for family in memory.get("families", {}).values():
        if isinstance(family, dict):
            recent_candidates = [
                candidate for candidate in family.get("recent_candidates", [])
                if isinstance(candidate, dict)
            ]
            for candidate in reversed(recent_candidates):
                if candidate.get("candidate_id") == candidate_id and not _is_mock_candidate(candidate):
                    return candidate
            for candidate in reversed(recent_candidates):
                if candidate.get("candidate_id") == candidate_id:
                    return candidate
            best = family.get("best_candidate")
            if isinstance(best, dict) and best.get("candidate_id") == candidate_id:
                return best
    return None


def _is_mock_candidate(candidate: Dict[str, Any]) -> bool:
    metrics = candidate.get("metrics", {})
    raw = metrics.get("raw", {}) if isinstance(metrics, dict) else {}
    return isinstance(raw, dict) and raw.get("mode") == "mock"


def _flat_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "recorded_at": report.get("recorded_at"),
        "candidate_id": report.get("candidate_id"),
        "family": report.get("family"),
        "result_id": report.get("result_id"),
        "decision": report.get("decision"),
        "overall_status": report.get("overall_status"),
        "blocking_checks": ",".join(report.get("blocking_checks", [])),
    }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _append_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _append_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
