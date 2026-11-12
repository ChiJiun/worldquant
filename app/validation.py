from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import csv
import json

from app.attribution import families_with_candidate, snapshot_matches
from app.correlations import (
    SELF_CORRELATION_THRESHOLD,
    load_correlation_cache,
    save_correlation_cache,
    self_correlation_fetched_at,
    self_correlation_max,
    update_correlation_cache,
)
from app.models import utc_now_iso
from app.research import load_family_memory, save_family_memory, update_candidate_metrics
from app.research_paths import ensure_research_layout


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


def validate_candidate_from_memory(
    research_dir: Path,
    candidate_id: Optional[str] = None,
    *,
    result_id: Optional[str] = None,
    persist: bool = False,
    refresh: bool = False,
    client: Any = None,
) -> Dict[str, Any]:
    """Build the validation report for a candidate stored in family memory.

    ``result_id`` disambiguates a ``candidate_id`` that was reused across families for different alphas;
    on its own it selects the snapshot carrying that BRAIN alpha id whatever its ``candidate_id``.
    With ``refresh`` the alpha is re-fetched from BRAIN through ``client`` (so PENDING platform checks can
    resolve), every stored snapshot of that exact alpha gets the new metrics, and its self-correlation is
    pulled into ``research/state/alpha_correlations.json``.
    """
    paths = ensure_research_layout(research_dir)
    memory = load_family_memory(research_dir)
    if not memory.get("families") and not memory.get("global_best"):
        raise ValueError(
            f"family_memory.json is missing or empty under {research_dir}; run `python -m app simulate` first"
        )
    candidate = _select_candidate(memory, candidate_id, result_id)
    if candidate is None:
        wanted = candidate_id or ("<any candidate>" if result_id else "<global_best>")
        if result_id:
            wanted += f" (result_id={result_id})"
        raise ValueError(f"Candidate not found in family_memory.json: {wanted}")
    duplicate_families = families_with_candidate(memory, str(candidate.get("candidate_id") or ""))

    refreshed: Optional[Dict[str, Any]] = None
    if refresh:
        candidate, refreshed = _refresh_candidate(research_dir, memory, candidate, client, paths.alpha_correlations)

    cache = load_correlation_cache(paths.alpha_correlations)
    report = _build_report(candidate, cache)
    if refreshed is not None:
        report["refreshed"] = refreshed
    if len(duplicate_families) > 1 and not result_id:
        report["warning"] = (
            f"candidate_id {candidate.get('candidate_id')} appears in families {duplicate_families}; "
            f"using result_id {candidate.get('result_id')} (pass --result-id to pick another alpha)"
        )
    if persist:
        _append_jsonl(paths.validation_reports_jsonl, [report])
        _append_csv(paths.validation_reports_csv, [_flat_report(report)])
    return report


def _refresh_candidate(
    research_dir: Path,
    memory: Dict[str, Any],
    candidate: Dict[str, Any],
    client: Any,
    cache_path: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if client is None:
        raise ValueError("refresh=True requires a BRAIN client")
    result_id = str(candidate.get("result_id") or "").strip()
    if not result_id:
        raise ValueError(f"Candidate {candidate.get('candidate_id')} has no result_id to refresh from BRAIN")
    metrics = client.fetch_result(result_id).as_dict()
    candidate_id = str(candidate.get("candidate_id") or "")
    updated = update_candidate_metrics(memory, candidate_id, metrics, result_id=result_id)
    save_family_memory(research_dir, memory)
    refreshed: Dict[str, Any] = {
        "result_id": result_id,
        "refreshed_at": utc_now_iso(),
        "updated_snapshots": updated,
    }
    fetch_self = getattr(client, "fetch_self_correlation", None)
    if callable(fetch_self):
        try:
            correlation = fetch_self(result_id)
        except Exception as exc:  # noqa: BLE001 - the metrics refresh already succeeded; report and continue
            refreshed["self_correlation_error"] = f"{exc.__class__.__name__}: {exc}"
        else:
            cache = load_correlation_cache(cache_path)
            update_correlation_cache(cache, correlation)
            save_correlation_cache(cache_path, cache)
            refreshed["self_correlation_max"] = correlation.max_correlation
    return dict(candidate, metrics=metrics), refreshed


def _build_report(candidate: Dict[str, Any], cache: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
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

    if checks["self_corr"]["status"] in {"pending", "missing", "needs_live_result"}:
        cached = _self_corr_from_cache(cache or {}, str(candidate.get("result_id") or ""))
        if cached is not None:
            checks["self_corr"] = cached

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


def _self_corr_from_cache(cache: Dict[str, Dict[str, Any]], result_id: str) -> Optional[Dict[str, str]]:
    """Use the cached BRAIN self-correlation when the stored platform check is still PENDING."""
    if not result_id:
        return None
    platform_max = self_correlation_max(cache, result_id)
    if platform_max is None:
        return None
    status = "fail" if platform_max >= SELF_CORRELATION_THRESHOLD else "pass"
    fetched_at = self_correlation_fetched_at(cache, result_id)
    return {
        "status": status,
        "reason": (
            f"BRAIN self-correlation max={platform_max:g} vs threshold {SELF_CORRELATION_THRESHOLD:g} "
            f"(from research/state/alpha_correlations.json, fetched_at={fetched_at or 'unknown'})"
        ),
        "source": "correlation_cache",
        "fetched_at": fetched_at,
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


def _select_candidate(
    memory: Dict[str, Any],
    candidate_id: Optional[str],
    result_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pick the snapshot to validate.

    Neither id given: the global best. ``candidate_id`` given: its latest snapshot (a live one is
    preferred over a mock one), optionally narrowed to ``result_id``. Only ``result_id`` given: the
    snapshot carrying that BRAIN alpha id, searched across every family, so the flag is never silently
    ignored.
    """
    wanted_result = str(result_id or "").strip()
    if not candidate_id and not wanted_result:
        best = memory.get("global_best")
        return best if isinstance(best, dict) else None

    def _matches(candidate: Any) -> bool:
        return snapshot_matches(candidate, candidate_id, wanted_result)

    families = memory.get("families", {}) if isinstance(memory.get("families"), dict) else {}
    for family in families.values():
        if isinstance(family, dict):
            recent_candidates = [
                candidate for candidate in family.get("recent_candidates", [])
                if isinstance(candidate, dict)
            ]
            for candidate in reversed(recent_candidates):
                if _matches(candidate) and not _is_mock_candidate(candidate):
                    return candidate
            for candidate in reversed(recent_candidates):
                if _matches(candidate):
                    return candidate
            best = family.get("best_candidate")
            if _matches(best):
                return best
    global_best = memory.get("global_best")
    if _matches(global_best):
        return global_best
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
