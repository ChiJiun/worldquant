from unittest.mock import Mock

import pytest

from app.api import MockBrainClient, RateLimiter, RequestsBrainClient
from app.models import AlphaCandidate


def make_candidate() -> AlphaCandidate:
    return AlphaCandidate(candidate_id="A_test", family="smoke", expression="rank(close)")


def test_mock_client_returns_metrics():
    client = MockBrainClient(RateLimiter(0.0))
    handle = client.simulate(make_candidate())
    payload = client.poll(handle.simulation_id)
    metrics = client.fetch_result(handle.simulation_id)
    assert payload["status"] == "complete"
    assert metrics.sharpe is not None
    assert metrics.fitness is not None


def test_requests_client_login_uses_basic_auth_in_auto_mode(settings):
    settings.auth_mode = "auto"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    response_ok = Mock(status_code=200, text="ok")
    client.session.post = Mock(return_value=response_ok)
    client.login()
    assert client.logged_in is True
    assert client.last_login_mode == "basic"
    _, kwargs = client.session.post.call_args
    assert kwargs["auth"] is not None
    assert kwargs["timeout"] == settings.request_timeout_seconds


def test_requests_client_uses_location_header_for_simulation_id(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    response = Mock(status_code=201, text="created", content=b"")
    response.headers = {"Location": "/simulations/sim-42"}
    client.session.post = Mock(return_value=response)
    handle = client.simulate(make_candidate())
    assert handle.simulation_id == "sim-42"


def test_requests_client_builds_worldquant_simulation_payload(settings):
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    payload = client._build_simulation_payload(make_candidate())
    assert payload["type"] == "REGULAR"
    assert payload["regular"] == "rank(close)"
    assert payload["settings"]["instrumentType"] == "EQUITY"
    assert payload["settings"]["region"] == "USA"


def test_requests_client_applies_candidate_simulation_settings(settings):
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    candidate = AlphaCandidate(
        candidate_id="A_settings",
        family="settings",
        expression="rank(close)",
        metadata={
            "simulation_settings": {
                "universe": "TOP1000",
                "delay": 0,
                "decay": 3,
                "truncation": 0.05,
                "neutralization": "MARKET",
                "lookback": 252,
                "max_trade": "ON",
                "maxPosition": "OFF",
            }
        },
    )

    payload = client._build_simulation_payload(candidate)

    assert payload["settings"]["universe"] == "TOP1000"
    assert payload["settings"]["delay"] == 0
    assert payload["settings"]["decay"] == 3
    assert payload["settings"]["truncation"] == 0.05
    assert payload["settings"]["neutralization"] == "MARKET"
    assert payload["settings"]["lookback"] == 252
    assert payload["settings"]["maxTrade"] == "ON"
    assert payload["settings"]["maxPosition"] == "OFF"


def test_requests_client_fetch_result_parses_alpha_metrics(settings):
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    alpha_response = Mock(status_code=200, content=b"{}")
    alpha_response.json.return_value = {
        "id": "alpha-1",
        "stage": "IS",
        "checks": [{"name": "LOW_SHARPE", "result": "FAIL"}],
        "is": {"sharpe": 1.2, "fitness": 1.1, "returns": 0.08, "drawdown": 0.04, "turnover": 0.3, "margin": 0.05},
    }
    client.session.get = Mock(return_value=alpha_response)

    metrics = client.fetch_result("alpha-1")

    assert metrics.alpha_id == "alpha-1"
    assert metrics.sharpe == 1.2
    assert metrics.checks_failed == 1


def test_requests_client_fetch_result_parses_nested_is_checks(settings):
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    alpha_response = Mock(status_code=200, content=b"{}")
    alpha_response.json.return_value = {
        "id": "alpha-1",
        "is": {
            "sharpe": 0.94,
            "fitness": 0.64,
            "checks": [{"name": "LOW_SHARPE", "result": "FAIL"}],
        },
    }
    client.session.get = Mock(return_value=alpha_response)

    metrics = client.fetch_result("alpha-1")

    assert metrics.sharpe == 0.94
    assert metrics.checks_failed == 1


def _correlation_response(status_code=200, payload=None, retry_after=None):
    response = Mock(status_code=status_code, content=b"{}" if payload is not None else b"", text="")
    response.json.return_value = payload if payload is not None else {}
    response.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return response


def test_requests_client_waits_for_retry_after_then_parses_self_correlation(settings, monkeypatch):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    payload = {
        "schema": {"properties": [{"name": "id"}, {"name": "correlation"}]},
        "records": [["alpha-9", 0.74]],
        "max": 0.74,
        "min": 0.74,
    }
    client.session.get = Mock(side_effect=[
        _correlation_response(retry_after="2.5"),
        _correlation_response(payload=payload),
    ])

    result = client.fetch_self_correlation("alpha-1")

    assert result.max_correlation == 0.74
    assert result.records == [{"id": "alpha-9", "correlation": 0.74}]
    assert sleeps == [2.5]
    called_paths = [call.args[0] for call in client.session.get.call_args_list]
    assert called_paths == ["https://example.com/alphas/alpha-1/correlations/self"] * 2


def test_requests_client_prod_correlation_uses_prod_path_and_raises_on_error(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    client.session.get = Mock(return_value=Mock(status_code=404, text="missing", content=b""))

    with pytest.raises(RuntimeError, match="prod correlation fetch failed"):
        client.fetch_prod_correlation("alpha-1")
    assert client.session.get.call_args.args[0] == "https://example.com/alphas/alpha-1/correlations/prod"


def test_requests_client_correlation_times_out_when_platform_keeps_computing(settings, monkeypatch):
    settings.auth_mode = "basic"
    settings.max_poll_attempts = 2
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: None)
    client.session.get = Mock(return_value=_correlation_response(retry_after="1"))

    with pytest.raises(TimeoutError, match="still computing"):
        client.fetch_self_correlation("alpha-1")


def test_mock_client_returns_preset_or_empty_correlation():
    client = MockBrainClient(RateLimiter(0.0))
    client.correlation_payloads[("alpha-1", "self")] = {"max": 0.9, "records": [{"id": "alpha-2", "correlation": 0.9}]}

    preset = client.fetch_self_correlation("alpha-1")
    empty = client.fetch_prod_correlation("alpha-1")

    assert preset.max_correlation == 0.9
    assert preset.records[0]["id"] == "alpha-2"
    assert empty.max_correlation == 0.0
    assert empty.records == []
