from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import json
import logging

from app.models import CorrelationResult, utc_now_iso

LOGGER = logging.getLogger(__name__)

# Version 1 caches may hold ``max_correlation: 0.0`` entries written by an early mock client, which
# look like a real platform number; bumping to 2 retires them (they are reloaded as empty and backed up).
CACHE_VERSION = 2
CACHE_STATUS_OK = "ok"
CACHE_STATUS_MISSING = "missing"
CACHE_STATUS_CORRUPT = "corrupt"
CACHE_STATUS_STALE_VERSION = "stale_version"
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
    """Return ``{alpha_id: {"self": {...}, "prod": {...}}}``.

    A missing file, a corrupt file or a file written by an older ``CACHE_VERSION`` all load as ``{}``
    (the latter two with a warning in the log); ``save_correlation_cache`` moves such a file aside
    instead of overwriting it.
    """
    status, payload = inspect_correlation_cache(path)
    if status == CACHE_STATUS_CORRUPT:
        LOGGER.warning("Correlation cache %s is not valid JSON; treating it as empty", path)
        return {}
    if status == CACHE_STATUS_STALE_VERSION:
        LOGGER.warning(
            "Correlation cache %s has version %s but this code expects %s; treating it as empty (rerun fetch-correlations)",
            path,
            payload.get("version") if isinstance(payload, dict) else None,
            CACHE_VERSION,
        )
        return {}
    if status != CACHE_STATUS_OK:
        return {}
    alphas = payload.get("alphas")
    return {str(key): value for key, value in alphas.items() if isinstance(value, dict)} if isinstance(alphas, dict) else {}


def inspect_correlation_cache(path: Path) -> Tuple[str, Any]:
    """Classify the cache file as ok / missing / corrupt / stale_version and return the parsed payload."""
    if not path.exists():
        return CACHE_STATUS_MISSING, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return CACHE_STATUS_CORRUPT, None
    if not isinstance(payload, dict):
        return CACHE_STATUS_CORRUPT, payload
    if payload.get("version") != CACHE_VERSION:
        return CACHE_STATUS_STALE_VERSION, payload
    return CACHE_STATUS_OK, payload


def save_correlation_cache(path: Path, cache: Dict[str, Dict[str, Any]]) -> Optional[Path]:
    """Write the cache; a corrupt or stale-version file at ``path`` is renamed first and its new path returned."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = backup_unusable_correlation_cache(path)
    payload = {"version": CACHE_VERSION, "updated_at": utc_now_iso(), "alphas": cache}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return backup


def backup_unusable_correlation_cache(path: Path) -> Optional[Path]:
    """Move a corrupt or stale-version cache file to ``<name>.corrupt`` / ``<name>.v<old>`` so it is not overwritten."""
    status, payload = inspect_correlation_cache(path)
    if status == CACHE_STATUS_CORRUPT:
        suffix = ".corrupt"
    elif status == CACHE_STATUS_STALE_VERSION:
        old_version = payload.get("version") if isinstance(payload, dict) else None
        suffix = f".v{old_version}" if isinstance(old_version, int) else ".stale"
    else:
        return None
    backup = path.with_name(path.name + suffix)
    counter = 1
    while backup.exists():
        counter += 1
        backup = path.with_name(f"{path.name}{suffix}.{counter}")
    path.rename(backup)
    LOGGER.warning("Moved unusable correlation cache %s to %s", path, backup)
    return backup


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


def self_correlation_fetched_at(cache: Dict[str, Dict[str, Any]], alpha_id: str) -> Optional[str]:
    """``fetched_at`` of a valued ``self`` entry; a valueless (mock smoke-run) entry has no platform number to date."""
    entry = cache.get(alpha_id, {}).get(SELF_KIND)
    if not isinstance(entry, dict) or _float(entry.get("max_correlation")) is None:
        return None
    value = entry.get("fetched_at")
    return str(value) if value else None


def oldest_fetched_at(cache: Dict[str, Dict[str, Any]], kind: str = SELF_KIND) -> Optional[str]:
    """Oldest ``fetched_at`` among valued ``kind`` entries, so reports can flag a stale cache."""
    stamps = []
    for entry in cache.values():
        item = entry.get(kind) if isinstance(entry, dict) else None
        if isinstance(item, dict) and item.get("max_correlation") is not None and item.get("fetched_at"):
            stamps.append(str(item["fetched_at"]))
    return min(stamps) if stamps else None


def is_cached(cache: Dict[str, Dict[str, Any]], alpha_id: str, kind: str) -> bool:
    """True when the cache holds a usable (valued) ``kind`` entry; valueless smoke-test entries are refetched."""
    entry = cache.get(alpha_id, {}).get(kind)
    return isinstance(entry, dict) and entry.get("max_correlation") is not None


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

    ``limit`` caps the number of API calls, failed calls included (entries skipped as cached do not
    count), so a rate-limited session can be resumed by re-running the command. Entries without a
    ``max_correlation`` value (for example written by the mock client) are not treated as cached.
    """
    for kind in kinds:
        if kind not in CORRELATION_KINDS:
            raise ValueError(f"Unknown correlation kind: {kind}")
    cache_status, _payload = inspect_correlation_cache(cache_path)
    cache = load_correlation_cache(cache_path)
    fetched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    requested = [alpha_id for alpha_id in dict.fromkeys(str(value).strip() for value in alpha_ids) if alpha_id]
    fetch_count = 0
    stopped_at_limit = False
    for alpha_id in requested:
        for kind in kinds:
            if not refresh and is_cached(cache, alpha_id, kind):
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
    backup = save_correlation_cache(cache_path, cache)
    report = {
        "cache_path": str(cache_path),
        "requested_alpha_count": len(requested),
        "fetched": fetched,
        "skipped": skipped,
        "errors": errors,
        "stopped_at_limit": stopped_at_limit,
        "cached_alpha_count": len(cache),
    }
    if backup is not None:
        report["previous_cache_status"] = cache_status
        report["previous_cache_backup"] = str(backup)
    return report


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
