from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import hashlib
import logging
import random
import time

import requests
from requests.auth import HTTPBasicAuth

from app.api.rate_limiter import RateLimiter
from app.config import Settings
from app.models import AlphaCandidate, SimulationHandle, SimulationMetrics

LOGGER = logging.getLogger(__name__)


class BrainClient(ABC):
    @abstractmethod
    def login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def simulate(self, candidate: AlphaCandidate, sim_config: Dict[str, Any]) -> SimulationHandle:
        raise NotImplementedError

    @abstractmethod
    def poll(self, simulation_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_result(self, result_id: str) -> SimulationMetrics:
        raise NotImplementedError

    def submit_candidate(self, alpha_id: str) -> Dict[str, Any]:
        return {"status": "manual-review", "alpha_id": alpha_id}


class RequestsBrainClient(BrainClient):
    def __init__(self, settings: Settings, rate_limiter: RateLimiter) -> None:
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.session = requests.Session()
        self.logged_in = False
        self.last_login_mode: Optional[str] = None

    def login(self) -> None:
        login_url = self.settings.api_base_url + self.settings.api_login_path
        errors = []
        for mode in self._auth_attempts():
            try:
                response = self._login_request(login_url, mode)
                if response.status_code >= 400:
                    errors.append(f"{mode}: {response.status_code} {response.text}")
                    continue
                self.logged_in = True
                self.last_login_mode = mode
                LOGGER.info("WorldQuant login succeeded using %s auth", mode)
                return
            except requests.RequestException as exc:
                errors.append(f"{mode}: {exc}")
        raise RuntimeError("Login failed across auth modes: " + " | ".join(errors))

    def _auth_attempts(self) -> List[str]:
        mode = self.settings.auth_mode.lower()
        if mode == "auto":
            return ["basic", "json", "form"]
        if mode not in {"basic", "json", "form"}:
            raise ValueError(f"Unknown auth mode: {self.settings.auth_mode}")
        return [mode]

    def _login_request(self, login_url: str, mode: str) -> requests.Response:
        self.rate_limiter.wait()
        if mode == "basic":
            return self.session.post(login_url, auth=HTTPBasicAuth(self.settings.username, self.settings.password), timeout=30)
        if mode == "json":
            return self.session.post(login_url, json={"username": self.settings.username, "password": self.settings.password}, timeout=30)
        return self.session.post(login_url, data={"username": self.settings.username, "password": self.settings.password}, timeout=30)

    def simulate(self, candidate: AlphaCandidate, sim_config: Dict[str, Any]) -> SimulationHandle:
        if not self.logged_in:
            self.login()
        self.rate_limiter.wait()
        payload = self._build_simulation_payload(candidate)
        response = self.session.post(self.settings.api_base_url + self.settings.api_simulate_path, json=payload, timeout=30)
        if response.status_code in {401, 403}:
            self.logged_in = False
            self.login()
            response = self.session.post(self.settings.api_base_url + self.settings.api_simulate_path, json=payload, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(self.settings.rate_limit_seconds)
            response = self.session.post(self.settings.api_base_url + self.settings.api_simulate_path, json=payload, timeout=30)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Simulation request failed: status={response.status_code} body={response.text[:1000]} payload={payload}"
            )
        data = {}
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        simulation_id = str(data.get("id") or data.get("simulation_id") or self._location_to_id(response.headers.get("Location", "")))
        if not simulation_id or simulation_id == "None":
            raise RuntimeError(f"Simulation did not return an id. status={response.status_code} body={response.text[:500]}")
        LOGGER.info("Simulation submitted simulation_id=%s expression=%s", simulation_id, candidate.expression)
        return SimulationHandle(simulation_id=simulation_id, submitted_at=datetime.now(timezone.utc), metadata={"response_json": data, "login_mode": self.last_login_mode})

    def poll(self, simulation_id: str) -> Dict[str, Any]:
        if not self.logged_in:
            self.login()
        self.rate_limiter.wait()
        path = self.settings.api_status_path.format(simulation_id=simulation_id)
        response = self.session.get(self.settings.api_base_url + path, timeout=30)
        if response.status_code in {401, 403}:
            self.logged_in = False
            self.login()
            response = self.session.get(self.settings.api_base_url + path, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(self.settings.rate_limit_seconds)
            response = self.session.get(self.settings.api_base_url + path, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_result(self, result_id: str) -> SimulationMetrics:
        if not self.logged_in:
            self.login()
        self.rate_limiter.wait()
        alpha_response = self.session.get(self.settings.api_base_url + f"/alphas/{result_id}", timeout=30)
        if alpha_response.status_code == 200:
            alpha_data = alpha_response.json()
            metrics = alpha_data.get("is") or alpha_data.get("train") or alpha_data.get("test") or {}
            stage_metrics = {}
            for stage in ("is", "train", "test"):
                if isinstance(alpha_data.get(stage), dict):
                    stage_metrics[stage] = {
                        "sharpe": float(alpha_data[stage].get("sharpe", 0.0)),
                        "fitness": float(alpha_data[stage].get("fitness", 0.0)),
                        "returns": float(alpha_data[stage].get("returns", 0.0)),
                        "drawdown": float(alpha_data[stage].get("drawdown", 0.0)),
                        "turnover": float(alpha_data[stage].get("turnover", 0.0)),
                        "margin": float(alpha_data[stage].get("margin", 0.0)),
                    }
            checks = alpha_data.get("checks", [])
            failed_checks = [
                check for check in checks
                if isinstance(check, dict) and str(check.get("result", "")).upper() == "FAIL"
            ]
            return SimulationMetrics(
                sharpe=float(metrics.get("sharpe", 0.0)),
                fitness=float(metrics.get("fitness", 0.0)),
                returns=float(metrics.get("returns", 0.0)),
                drawdown=float(metrics.get("drawdown", 0.0)),
                turnover=float(metrics.get("turnover", 0.0)),
                margin=float(metrics.get("margin", 0.0)),
                extras={
                    **{k: v for k, v in metrics.items() if k not in {"sharpe", "fitness", "returns", "drawdown", "turnover", "margin"}},
                    "alpha_id": alpha_data.get("id", result_id),
                    "grade": alpha_data.get("grade"),
                    "stage": alpha_data.get("stage") or alpha_data.get("status") or "is",
                    "status": alpha_data.get("status"),
                    "universe": alpha_data.get("settings", {}).get("universe", self.settings.universe),
                    "region": alpha_data.get("settings", {}).get("region", self.settings.region),
                    "delay": alpha_data.get("settings", {}).get("delay", self.settings.delay),
                    "neutralization": alpha_data.get("settings", {}).get("neutralization", self.settings.neutralization),
                    "checks": checks,
                    "checks_failed": len(failed_checks),
                    "failed_check_names": [
                        str(check.get("name", check.get("label", "unknown")))
                        for check in failed_checks
                    ],
                    "stage_metrics": stage_metrics,
                    "classifications": alpha_data.get("classifications", {}),
                },
            )
        self.rate_limiter.wait()
        path = self.settings.api_result_path.format(simulation_id=result_id)
        response = self.session.get(self.settings.api_base_url + path, timeout=30)
        if response.status_code in {401, 403}:
            self.logged_in = False
            self.login()
            response = self.session.get(self.settings.api_base_url + path, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(self.settings.rate_limit_seconds)
            response = self.session.get(self.settings.api_base_url + path, timeout=30)
        response.raise_for_status()
        data = response.json()
        return SimulationMetrics(
            sharpe=float(data.get("sharpe", 0.0)),
            fitness=float(data.get("fitness", 0.0)),
            returns=float(data.get("returns", 0.0)),
            drawdown=float(data.get("drawdown", 0.0)),
            turnover=float(data.get("turnover", 0.0)),
            margin=float(data.get("margin", 0.0)),
            extras={k: v for k, v in data.items() if k not in {"sharpe", "fitness", "returns", "drawdown", "turnover", "margin"}},
        )

    def _build_simulation_payload(self, candidate: AlphaCandidate) -> Dict[str, Any]:
        return {
            "type": self.settings.simulation_type,
            "settings": self.settings.simulation_settings_payload(),
            "regular": candidate.expression,
        }

    @staticmethod
    def _location_to_id(location: str) -> str:
        if not location:
            return ""
        return location.rstrip("/").split("/")[-1]


class PyWorldQuantClient(RequestsBrainClient):
    def __init__(self, settings: Settings, rate_limiter: RateLimiter) -> None:
        super().__init__(settings, rate_limiter)
        self._backend: Optional[Any] = None
        try:
            import pyworldquant  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyworldquant is not installed") from exc
        self._backend = pyworldquant

    def login(self) -> None:
        if self._backend and hasattr(self._backend, "login"):
            self.rate_limiter.wait()
            self._backend.login(self.settings.username, self.settings.password)
            self.logged_in = True
            self.last_login_mode = "pyworldquant"
            return
        super().login()


class MockBrainClient(BrainClient):
    def __init__(self, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.rate_limiter = rate_limiter or RateLimiter(0.0)
        self.random = random.Random(23)
        self.results: Dict[str, SimulationMetrics] = {}

    def login(self) -> None:
        return None

    def simulate(self, candidate: AlphaCandidate, sim_config: Dict[str, Any]) -> SimulationHandle:
        self.rate_limiter.wait()
        simulation_id = hashlib.md5(candidate.expression.encode("utf-8")).hexdigest()[:12]
        base = sum(ord(char) for char in candidate.expression) % 100
        metrics = SimulationMetrics(
            sharpe=round(0.7 + (base % 9) * 0.12, 4),
            fitness=round(0.5 + (base % 11) * 0.1, 4),
            returns=round(0.02 + (base % 8) * 0.01, 4),
            drawdown=round(0.01 + (base % 5) * 0.015, 4),
            turnover=round(0.1 + (base % 6) * 0.03, 4),
            margin=round(0.03 + (base % 7) * 0.01, 4),
        )
        self.results[simulation_id] = metrics
        return SimulationHandle(simulation_id=simulation_id, submitted_at=datetime.now(timezone.utc), metadata={"mode": sim_config.get("mode", "mock")})

    def poll(self, simulation_id: str) -> Dict[str, Any]:
        self.rate_limiter.wait()
        return {"status": "complete", "simulation_id": simulation_id}

    def fetch_result(self, result_id: str) -> SimulationMetrics:
        self.rate_limiter.wait()
        return self.results[result_id]


def build_client(settings: Settings, rate_limiter: RateLimiter) -> BrainClient:
    mode = settings.client_mode.lower()
    if mode == "mock" or settings.dry_run:
        return MockBrainClient(rate_limiter)
    if mode == "pyworldquant":
        return PyWorldQuantClient(settings, rate_limiter)
    if mode == "requests":
        return RequestsBrainClient(settings, rate_limiter)
    if mode == "auto":
        try:
            return PyWorldQuantClient(settings, rate_limiter)
        except Exception as exc:
            LOGGER.warning("Falling back to requests client: %s", exc)
            return RequestsBrainClient(settings, rate_limiter)
    raise ValueError(f"Unknown client mode: {settings.client_mode}")
