from unittest.mock import Mock

from app.api import MockBrainClient, RateLimiter, RequestsBrainClient
from app.models import AlphaCandidate, ExpressionNode


def make_candidate() -> AlphaCandidate:
    tree = ExpressionNode(kind="operator", value="rank", children=[ExpressionNode(kind="field", value="close")])
    return AlphaCandidate(expression=tree.to_expression(), tree=tree, template_type="momentum", params={"field_1": "close"}, wrappers=["rank"])


def test_mock_client_returns_metrics():
    client = MockBrainClient(RateLimiter(0.0))
    handle = client.simulate(make_candidate(), {"mode": "test"})
    payload = client.poll(handle.simulation_id)
    metrics = client.fetch_result(handle.simulation_id)
    assert payload["status"] == "complete"
    assert metrics.sharpe > 0
    assert metrics.fitness > 0


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


def test_requests_client_retries_after_relogin(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    login_ok = Mock(status_code=200, text="ok")
    response_unauthorized = Mock(status_code=401, text="unauthorized")
    response_ok = Mock(status_code=200, text="ok")
    response_ok.content = b'{"id":"sim-1"}'
    response_ok.json.return_value = {"id": "sim-1"}
    client.session.post = Mock(side_effect=[login_ok, response_unauthorized, login_ok, response_ok])
    handle = client.simulate(make_candidate(), {"mode": "test"})
    assert handle.simulation_id == "sim-1"
    assert client.session.post.call_count == 4


def test_requests_client_uses_location_header_for_simulation_id(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    response = Mock(status_code=201, text="created", content=b"")
    response.headers = {"Location": "/simulations/sim-42"}
    client.session.post = Mock(return_value=response)
    handle = client.simulate(make_candidate(), {"mode": "test"})
    assert handle.simulation_id == "sim-42"


def test_requests_client_builds_worldquant_simulation_payload(settings):
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    payload = client._build_simulation_payload(make_candidate())
    assert payload["type"] == "REGULAR"
    assert payload["regular"] == "rank(close)"
    assert payload["settings"]["instrumentType"] == "EQUITY"
    assert payload["settings"]["region"] == "USA"


def test_requests_client_fetch_result_enriches_stage_metadata(settings):
    settings.auth_mode = "basic"
    client = RequestsBrainClient(settings, RateLimiter(0.0))
    client.logged_in = True
    alpha_response = Mock(status_code=200)
    alpha_response.json.return_value = {
        "id": "alpha-1",
        "stage": "IS",
        "status": "COMPLETE",
        "settings": {"universe": "TOP1000", "region": "USA", "delay": 1, "neutralization": "INDUSTRY"},
        "checks": [{"name": "LOW_SHARPE", "result": "FAIL"}],
        "is": {"sharpe": 1.2, "fitness": 1.1, "returns": 0.08, "drawdown": 0.04, "turnover": 0.3, "margin": 0.05},
        "train": {"sharpe": 1.0, "fitness": 0.9, "returns": 0.06, "drawdown": 0.05, "turnover": 0.25, "margin": 0.04},
    }
    client.session.get = Mock(return_value=alpha_response)

    metrics = client.fetch_result("alpha-1")

    assert metrics.sharpe == 1.2
    assert metrics.extras["stage"] == "IS"
    assert metrics.extras["universe"] == "TOP1000"
    assert metrics.extras["checks_failed"] == 1
    assert "train" in metrics.extras["stage_metrics"]
