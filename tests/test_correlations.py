import json
from pathlib import Path

import pytest

from app.api import MockBrainClient, RateLimiter
from app.correlations import (
    fetch_correlations,
    load_correlation_cache,
    parse_correlation_payload,
    save_correlation_cache,
    self_correlation_between,
    self_correlation_max,
    top_self_correlated,
    update_correlation_cache,
)


SELF_PAYLOAD = {
    "schema": {
        "name": "self_correlation",
        "properties": [
            {"name": "id"},
            {"name": "name"},
            {"name": "correlation"},
            {"name": "sharpe"},
        ],
    },
    "records": [
        ["alpha-9", "old reversal", 0.81, 1.4],
        ["alpha-7", "value", -0.35, 1.1],
        ["alpha-5", None, 0.12, 0.9],
    ],
    "max": 0.81,
    "min": -0.35,
}

PROD_PAYLOAD = {
    "schema": {"properties": [{"name": "min"}, {"name": "max"}, {"name": "alphas"}]},
    "records": [[-1.0, -0.9, 0], [0.5, 0.6, 3], [0.6, 0.7, 1], [0.9, 1.0, 0]],
}


def test_parse_self_payload_zips_schema_and_keeps_extremes():
    result = parse_correlation_payload("alpha-1", "self", SELF_PAYLOAD)

    assert result.kind == "self"
    assert result.max_correlation == 0.81
    assert result.min_correlation == -0.35
    assert result.records[0] == {"id": "alpha-9", "name": "old reversal", "correlation": 0.81, "sharpe": 1.4}
    assert result.fetched_at.endswith("Z")


def test_parse_self_payload_derives_max_when_platform_omits_it():
    payload = {k: v for k, v in SELF_PAYLOAD.items() if k not in {"max", "min"}}

    result = parse_correlation_payload("alpha-1", "self", payload)

    assert result.max_correlation == 0.81
    assert result.min_correlation == -0.35


def test_parse_prod_payload_uses_populated_buckets():
    result = parse_correlation_payload("alpha-1", "prod", PROD_PAYLOAD)

    assert result.max_correlation == 0.7
    assert result.min_correlation == 0.5


def test_parse_rejects_unknown_kind():
    with pytest.raises(ValueError):
        parse_correlation_payload("alpha-1", "other", {})


def test_cache_roundtrip_and_lookups(tmp_path):
    cache_path = tmp_path / "state" / "alpha_correlations.json"
    cache = {}
    update_correlation_cache(cache, parse_correlation_payload("alpha-1", "self", SELF_PAYLOAD))
    save_correlation_cache(cache_path, cache)

    loaded = load_correlation_cache(cache_path)

    assert self_correlation_max(loaded, "alpha-1") == 0.81
    assert self_correlation_max(loaded, "missing") is None
    assert top_self_correlated(loaded, "alpha-1")["alpha_id"] == "alpha-9"
    assert self_correlation_between(loaded, "alpha-1", "alpha-9") == 0.81
    assert self_correlation_between(loaded, "alpha-7", "alpha-1") == 0.35
    assert self_correlation_between(loaded, "alpha-1", "unknown") is None
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert "raw" not in payload["alphas"]["alpha-1"]["self"]


def test_load_cache_tolerates_corrupt_file(tmp_path):
    cache_path = tmp_path / "alpha_correlations.json"
    cache_path.write_text("{not json", encoding="utf-8")

    assert load_correlation_cache(cache_path) == {}


def test_fetch_correlations_skips_cached_respects_limit_and_records_errors(tmp_path):
    cache_path = tmp_path / "research" / "state" / "alpha_correlations.json"
    class FlakyClient(MockBrainClient):
        def fetch_self_correlation(self, alpha_id):
            if alpha_id == "alpha-bad":
                raise RuntimeError("boom")
            return super().fetch_self_correlation(alpha_id)

    flaky = FlakyClient(RateLimiter(0.0))
    flaky.correlation_payloads[("alpha-1", "self")] = SELF_PAYLOAD

    first = fetch_correlations(flaky, ["alpha-1", "alpha-bad", "alpha-3", "alpha-1"], cache_path, limit=2)

    assert first["requested_alpha_count"] == 3
    assert [item["alpha_id"] for item in first["fetched"]] == ["alpha-1"]
    assert first["errors"][0]["alpha_id"] == "alpha-bad"
    assert first["stopped_at_limit"] is True
    assert load_correlation_cache(cache_path)["alpha-1"]["self"]["max_correlation"] == 0.81

    second = fetch_correlations(flaky, ["alpha-1", "alpha-3"], cache_path, kinds=("self", "prod"))

    assert {(item["alpha_id"], item["kind"]) for item in second["skipped"]} == {("alpha-1", "self")}
    assert {(item["alpha_id"], item["kind"]) for item in second["fetched"]} == {("alpha-1", "prod"), ("alpha-3", "self"), ("alpha-3", "prod")}
    assert second["cached_alpha_count"] == 2
