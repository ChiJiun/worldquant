from unittest.mock import Mock

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
