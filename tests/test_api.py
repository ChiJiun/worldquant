from unittest.mock import Mock

import pytest

from app.api import MockBrainClient, RateLimiter, RequestsBrainClient, ThrottledError
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


def _correlation_response(status_code=200, payload=None, retry_after=None, text=""):
    response = Mock(status_code=status_code, content=b"{}" if payload is not None else b"", text=text)
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
    assert empty.max_correlation is None
    assert empty.records == []


@pytest.mark.parametrize(
    ("poll_interval", "retry_after", "expected"),
    [
        (5.0, "30", 30.0),  # honour the platform when it asks for longer than our interval
        (5.0, "2", 5.0),  # never poll faster than the configured interval
        (5.0, "Wed, 21 Oct 2026 07:28:00 GMT", 5.0),  # unparsable header -> configured interval
        (5.0, "-3", 5.0),
        (0.0, "30", 30.0),
        (0.0, "abc", 1.0),  # no interval configured and no usable header -> one second, never a hot loop
        (0.0, "0.2", 1.0),  # the one-second floor also applies to a tiny Retry-After
        (5.0, "600", 60.0),  # capped so a huge Retry-After cannot hang the run
        (120.0, "30", 120.0),  # a poll interval above the cap still wins: never poll faster than configured
        (120.0, "600", 120.0),
    ],
)
def test_requests_client_retry_delay_respects_platform_and_floor(settings, poll_interval, retry_after, expected):
    settings.poll_interval_seconds = poll_interval
    client = RequestsBrainClient(settings, RateLimiter(0.0))

    assert client._retry_delay(retry_after) == expected


SELF_CORRELATION_PAYLOAD = {
    "schema": {"properties": [{"name": "id"}, {"name": "correlation"}]},
    "records": [["alpha-9", 0.42]],
    "max": 0.42,
    "min": 0.42,
}


def _throttled(retry_after=None):
    return _correlation_response(status_code=429, retry_after=retry_after, text='{"detail":"THROTTLED"}')


def _logged_in_client(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    return client


def test_requests_client_retries_429_honouring_retry_after_without_using_poll_attempts(settings, monkeypatch):
    settings.max_poll_attempts = 1
    client = _logged_in_client(settings)
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    client.session.get = Mock(side_effect=[
        _throttled(retry_after="7"),
        _throttled(retry_after="3"),
        _correlation_response(payload=SELF_CORRELATION_PAYLOAD),
    ])

    result = client.fetch_self_correlation("alpha-1")

    assert result.max_correlation == 0.42
    assert sleeps == [7.0, 3.0]
    assert client.session.get.call_count == 3


def test_requests_client_429_without_usable_retry_after_backs_off_exponentially(settings, monkeypatch):
    client = _logged_in_client(settings)
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    client.session.get = Mock(side_effect=[
        _throttled(),
        _throttled(retry_after="Wed, 21 Oct 2026 07:28:00 GMT"),
        _throttled(retry_after="0"),
        _correlation_response(payload=SELF_CORRELATION_PAYLOAD),
    ])

    result = client.fetch_self_correlation("alpha-1")

    assert result.max_correlation == 0.42
    assert sleeps == [10.0, 20.0, 40.0]


def test_requests_client_429_after_relogin_is_retried(settings, monkeypatch):
    client = _logged_in_client(settings)
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: None)
    client.login = Mock()
    client.session.get = Mock(side_effect=[
        _correlation_response(status_code=401),
        _throttled(retry_after="2"),
        _correlation_response(payload=SELF_CORRELATION_PAYLOAD),
    ])

    assert client.fetch_self_correlation("alpha-1").max_correlation == 0.42
    client.login.assert_called_once()


def test_requests_client_gives_up_after_max_throttle_retries(settings, monkeypatch):
    monkeypatch.setattr("app.api.clients.THROTTLE_MAX_RETRIES", 3)
    client = _logged_in_client(settings)
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    client.session.get = Mock(return_value=_throttled(retry_after="1"))

    with pytest.raises(ThrottledError, match="still throttled after 3 retries") as excinfo:
        client.fetch_self_correlation("alpha-1")

    assert isinstance(excinfo.value, RuntimeError)
    assert "THROTTLED" in str(excinfo.value)
    assert sleeps == [1.0, 1.0, 1.0]
    assert client.session.get.call_count == 4


def test_requests_client_gives_up_when_next_throttle_wait_exceeds_total_budget(settings, monkeypatch):
    monkeypatch.setattr("app.api.clients.THROTTLE_MAX_TOTAL_WAIT_SECONDS", 25.0)
    client = _logged_in_client(settings)
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    client.session.get = Mock(return_value=_throttled(retry_after="10"))

    with pytest.raises(ThrottledError, match=r"2 retries \(20s waited\)"):
        client.fetch_prod_correlation("alpha-1")

    assert sleeps == [10.0, 10.0]  # a third 10s wait would push the total to 30s > 25s


def test_requests_client_non_throttle_error_still_raises_immediately(settings, monkeypatch):
    client = _logged_in_client(settings)
    sleeps = []
    monkeypatch.setattr("app.api.clients.time.sleep", lambda seconds: sleeps.append(seconds))
    client.session.get = Mock(return_value=_correlation_response(status_code=500, text="server error"))

    with pytest.raises(RuntimeError, match="status=500") as excinfo:
        client.fetch_self_correlation("alpha-1")

    assert not isinstance(excinfo.value, ThrottledError)
    assert sleeps == []


@pytest.mark.parametrize(
    ("retry_after", "retries_so_far", "expected"),
    [
        ("30", 0, 30.0),  # honour the platform
        ("0.2", 0, 1.0),  # never below one second
        ("100000", 0, 300.0),  # capped so one header cannot stall the run
        (None, 0, 10.0),  # no header: exponential backoff from the base
        (None, 2, 40.0),
        (None, 10, 300.0),  # backoff is capped too
        ("abc", 1, 20.0),  # unparsable header falls back to backoff
        ("-5", 0, 10.0),
        ("nan", 0, 10.0),
        ("inf", 0, 300.0),
    ],
)
def test_requests_client_throttle_delay(retry_after, retries_so_far, expected):
    assert RequestsBrainClient._throttle_delay(retry_after, retries_so_far) == expected
