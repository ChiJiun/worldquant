from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import json

from app.models import CorrelationResult, utc_now_iso

CACHE_VERSION = 1
# BRAIN's SELF_CORRELATION submission check fails at or above this value.
SELF_CORRELATION_THRESHOLD = 0.7
RECORD_ID_KEYS = ("id", "alpha_id", "alphaId", "alpha")
SELF_KIND = "self"
PROD_KIND = "prod"
CORRELATION_KINDS = (SELF_KIND, PROD_KIND)


def parse_correlation_payload(alpha_id: str, kind: str, data: Dict[str, Any]) -> CorrelationResult:
    """Normalize a BRAIN /alphas/{id}/correlations/{self|prod} payload.

    BRAIN returns ``{"schema": {"properties": [{"name": ...}, ...]}, "records": [[...], ...], "max": x, "min": y}``.
    Records are positional lists, so they are zipped with the schema property names. For ``prod`` the
    records are histogram buckets (``min``/``max``/``alphas``), so the extremes are derived from the
    buckets that contain at least one alpha when the top-level ``max``/``min`` are missing.
    """
    if kind not in CORRELATION_KINDS:
        raise ValueError(f"Unknown correlation kind: {kind}")
    names = _schema_property_names(data.get("schema"))
    records: List[Dict[str, Any]] = []
    for item in data.get("records") or []:
        if isinstance(item, dict):
            records.append(item)
        elif isinstance(item, (list, tuple)) and names:
            records.append(dict(zip(names, item)))
    max_corr = _float(data.get("max"))
    min_corr = _float(data.get("min"))
    if kind == PROD_KIND:
        bucket_max, bucket_min = _prod_bucket_extremes(records)
        max_corr = max_corr if max_corr is not None else bucket_max
        min_corr = min_corr if min_corr is not None else bucket_min
    else:
        values = [value for value in (_float(record.get("correlation")) for record in records) if value is not None]
        if max_corr is None and values:
            max_corr = max(values)
        if min_corr is None and values:
            min_corr = min(values)
    return CorrelationResult(
        alpha_id=alpha_id,
        kind=kind,
        max_correlation=max_corr,
        min_correlation=min_corr,
        records=records,
        raw=data,
        fetched_at=utc_now_iso(),
    )


def load_correlation_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    """Return ``{alpha_id: {"self": {...}, "prod": {...}}}`` or ``{}`` when the cache is absent/corrupt."""
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    alphas = payload.get("alphas") if isinstance(payload, dict) else None
    return {str(key): value for key, value in alphas.items() if isinstance(value, dict)} if isinstance(alphas, dict) else {}


def save_correlation_cache(path: Path, cache: Dict[str, Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": CACHE_VERSION, "updated_at": utc_now_iso(), "alphas": cache}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def update_correlation_cache(cache: Dict[str, Dict[str, Any]], result: CorrelationResult) -> None:
    cache.setdefault(result.alpha_id, {})[result.kind] = result.as_dict()


def self_correlation_max(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> Optional[float]:
    entry = cache.get(alpha_id, {}).get(SELF_KIND)
    return _float(entry.get("max_correlation")) if isinstance(entry, dict) else None


def prod_correlation_max(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> Optional[float]:
    entry = cache.get(alpha_id, {}).get(PROD_KIND)
    return _float(entry.get("max_correlation")) if isinstance(entry, dict) else None


def has_self_correlation(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> bool:
    return self_correlation_max(cache, alpha_id) is not None


def top_self_correlated(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> Optional[Dict[str, Any]]:
    """The platform alpha most positively correlated with ``alpha_id`` according to the self-correlation records."""
    best: Optional[Dict[str, Any]] = None
    best_value: Optional[float] = None
    for record in _self_records(cache, alpha_id):
        value = _float(record.get("correlation"))
        other_id = _record_id(record)
        if value is None or not other_id:
            continue
        if best_value is None or value > best_value:
            best_value = value
            best = {**record, "alpha_id": other_id, "correlation": value}
    return best


def self_correlation_between(cache: Dict[str, Dict[str, Any]], left_id: str, right_id: str) -> Optional[float]:
    """Absolute platform correlation between two alphas when either side's self-correlation lists the other."""
    values: List[float] = []
    for source, target in ((left_id, right_id), (right_id, left_id)):
        for record in _self_records(cache, source):
            if _record_id(record) == target:
                value = _float(record.get("correlation"))
                if value is not None:
                    values.append(abs(value))
    return max(values) if values else None


def fetch_correlations(
    client: Any,
    alpha_ids: Sequence[str],
    cache_path: Path,
    *,
    kinds: Sequence[str] = (SELF_KIND,),
    refresh: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch correlation payloads for ``alpha_ids`` and merge them into the JSON cache.

    ``limit`` caps the number of API fetches (cached entries that are skipped do not count), so a
    rate-limited session can be resumed by re-running the command.
    """
    for kind in kinds:
        if kind not in CORRELATION_KINDS:
            raise ValueError(f"Unknown correlation kind: {kind}")
    cache = load_correlation_cache(cache_path)
    fetched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    requested = [alpha_id for alpha_id in dict.fromkeys(str(value).strip() for value in alpha_ids) if alpha_id]
    fetch_count = 0
    stopped_at_limit = False
    for alpha_id in requested:
        for kind in kinds:
            if not refresh and isinstance(cache.get(alpha_id, {}).get(kind), dict):
                skipped.append({"alpha_id": alpha_id, "kind": kind, "reason": "cached"})
                continue
            if limit is not None and fetch_count >= limit:
                stopped_at_limit = True
                continue
            fetch_count += 1
            try:
                result = client.fetch_self_correlation(alpha_id) if kind == SELF_KIND else client.fetch_prod_correlation(alpha_id)
            except Exception as exc:  # noqa: BLE001 - keep going and report per alpha
                errors.append({"alpha_id": alpha_id, "kind": kind, "error_type": exc.__class__.__name__, "error": str(exc)})
                continue
            update_correlation_cache(cache, result)
            fetched.append({
                "alpha_id": alpha_id,
                "kind": kind,
                "max_correlation": result.max_correlation,
                "min_correlation": result.min_correlation,
                "record_count": len(result.records),
            })
    save_correlation_cache(cache_path, cache)
    return {
        "cache_path": str(cache_path),
        "requested_alpha_count": len(requested),
        "fetched": fetched,
        "skipped": skipped,
        "errors": errors,
        "stopped_at_limit": stopped_at_limit,
        "cached_alpha_count": len(cache),
    }


def _self_records(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> List[Dict[str, Any]]:
    entry = cache.get(alpha_id, {}).get(SELF_KIND)
    records = entry.get("records") if isinstance(entry, dict) else None
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def _record_id(record: Dict[str, Any]) -> str:
    for key in RECORD_ID_KEYS:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _schema_property_names(schema: Any) -> List[str]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, list):
        return []
    return [str(item.get("name")) for item in properties if isinstance(item, dict) and item.get("name")]


def _prod_bucket_extremes(records: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    bucket_max: Optional[float] = None
    bucket_min: Optional[float] = None
    for record in records:
        count = _float(record.get("alphas"))
        if count is None or count <= 0:
            continue
        upper = _float(record.get("max"))
        lower = _float(record.get("min"))
        if upper is not None and (bucket_max is None or upper > bucket_max):
            bucket_max = upper
        if lower is not None and (bucket_min is None or lower < bucket_min):
            bucket_min = lower
    return bucket_max, bucket_min


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
