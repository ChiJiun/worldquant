from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import hashlib
import logging
import random

import requests
from requests.auth import HTTPBasicAuth

from app.api.rate_limiter import RateLimiter
from app.config import Settings
from app.models import AlphaCandidate, SimulationHandle, SimulationMetrics, utc_now_iso

LOGGER = logging.getLogger(__name__)


class BrainClient(ABC):
    @abstractmethod
    def login(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def simulate(self, candidate: AlphaCandidate) -> SimulationHandle:
        raise NotImplementedError

    @abstractmethod
    def poll(self, simulation_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_result(self, result_id: str) -> SimulationMetrics:
        raise NotImplementedError


class RequestsBrainClient(BrainClient):
    def __init__(self, settings: Settings, rate_limiter: RateLimiter) -> None:
        self.settings = settings
        self.rate_limiter = rate_limiter
        self.session = requests.Session()
        self.logged_in = False
        self.last_login_mode: Optional[str] = None

    def login(self) -> None:
        login_url = self.settings.api_base_url + self.settings.api_login_path
        errors: List[str] = []
        for mode in self._auth_attempts():
            try:
                response = self._login_request(login_url, mode)
                if response.status_code >= 400:
                    errors.append(f"{mode}: {response.status_code} {response.text[:500]}")
                    continue
                self.logged_in = True
                self.last_login_mode = mode
                LOGGER.info("WorldQuant login succeeded using %s auth", mode)
                return
            except requests.RequestException as exc:
                errors.append(f"{mode}: {exc}")
        raise RuntimeError("Login failed across auth modes: " + " | ".join(errors))

    def simulate(self, candidate: AlphaCandidate) -> SimulationHandle:
        if not self.logged_in:
            self.login()
        payload = self._build_simulation_payload(candidate)
        response = self._post(self.settings.api_simulate_path, payload)
        if response.status_code in {401, 403}:
            self.logged_in = False
            self.login()
            response = self._post(self.settings.api_simulate_path, payload)
        if response.status_code >= 400:
            raise RuntimeError(f"Simulation submit failed: status={response.status_code} body={response.text[:1000]}")
        data = self._safe_json(response)
        simulation_id = str(data.get("id") or data.get("simulation_id") or self._location_to_id(response.headers.get("Location", "")))
        if not simulation_id or simulation_id == "None":
            raise RuntimeError(f"Simulation submit did not return an id. status={response.status_code} body={response.text[:500]}")
        return SimulationHandle(
            simulation_id=simulation_id,
            submitted_at=utc_now_iso(),
            metadata={"response_json": data, "login_mode": self.last_login_mode},
        )

    def poll(self, simulation_id: str) -> Dict[str, Any]:
        if not self.logged_in:
            self.login()
        path = self.settings.api_status_path.format(simulation_id=simulation_id)
        response = self._get(path)
        if response.status_code in {401, 403}:
            self.logged_in = False
            self.login()
            response = self._get(path)
        if response.status_code >= 400:
            raise RuntimeError(f"Simulation poll failed: status={response.status_code} body={response.text[:1000]}")
        return self._safe_json(response)

    def fetch_result(self, result_id: str) -> SimulationMetrics:
        if not self.logged_in:
            self.login()
        alpha_response = self._get(f"/alphas/{result_id}")
        if alpha_response.status_code == 200:
            return self._metrics_from_alpha(result_id, self._safe_json(alpha_response))
        path = self.settings.api_result_path.format(simulation_id=result_id)
        response = self._get(path)
        if response.status_code >= 400:
            raise RuntimeError(f"Simulation result fetch failed: status={response.status_code} body={response.text[:1000]}")
        data = self._safe_json(response)
        return self._metrics_from_flat(result_id, data)

    def _auth_attempts(self) -> List[str]:
        mode = self.settings.auth_mode.lower()
        if mode == "auto":
            return ["basic", "json", "form"]
        if mode not in {"basic", "json", "form"}:
            raise ValueError(f"Unknown auth mode: {self.settings.auth_mode}")
        return [mode]

    def _login_request(self, login_url: str, mode: str) -> requests.Response:
        self.rate_limiter.wait()
        timeout = self.settings.request_timeout_seconds
        if mode == "basic":
            return self.session.post(login_url, auth=HTTPBasicAuth(self.settings.username, self.settings.password), timeout=timeout)
        if mode == "json":
            return self.session.post(login_url, json={"username": self.settings.username, "password": self.settings.password}, timeout=timeout)
        return self.session.post(login_url, data={"username": self.settings.username, "password": self.settings.password}, timeout=timeout)

    def _post(self, path: str, payload: Dict[str, Any]) -> requests.Response:
        self.rate_limiter.wait()
        return self.session.post(self.settings.api_base_url + path, json=payload, timeout=self.settings.request_timeout_seconds)

    def _get(self, path: str) -> requests.Response:
        self.rate_limiter.wait()
        return self.session.get(self.settings.api_base_url + path, timeout=self.settings.request_timeout_seconds)

    def _build_simulation_payload(self, candidate: AlphaCandidate) -> Dict[str, Any]:
        return {
            "type": self.settings.simulation_type,
            "settings": self.settings.simulation_settings_payload(),
            "regular": candidate.expression,
        }

    @staticmethod
    def _safe_json(response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {"data": data}

    @staticmethod
    def _location_to_id(location: str) -> str:
        return location.rstrip("/").split("/")[-1] if location else ""

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _metrics_from_alpha(self, result_id: str, data: Dict[str, Any]) -> SimulationMetrics:
        metrics = data.get("is") or data.get("train") or data.get("test") or data
        checks = data.get("checks", [])
        failed_checks = [
            check for check in checks
            if isinstance(check, dict) and str(check.get("result", "")).upper() == "FAIL"
        ]
        return SimulationMetrics(
            alpha_id=str(data.get("id") or result_id),
            status=str(data.get("stage") or data.get("status") or ""),
            sharpe=self._float_or_none(metrics.get("sharpe")),
            fitness=self._float_or_none(metrics.get("fitness")),
            returns=self._float_or_none(metrics.get("returns")),
            drawdown=self._float_or_none(metrics.get("drawdown")),
            turnover=self._float_or_none(metrics.get("turnover")),
            margin=self._float_or_none(metrics.get("margin")),
            checks_failed=len(failed_checks),
            raw=data,
        )

    def _metrics_from_flat(self, result_id: str, data: Dict[str, Any]) -> SimulationMetrics:
        return SimulationMetrics(
            alpha_id=str(data.get("alpha_id") or data.get("id") or result_id),
            status=str(data.get("status") or ""),
            sharpe=self._float_or_none(data.get("sharpe")),
            fitness=self._float_or_none(data.get("fitness")),
            returns=self._float_or_none(data.get("returns")),
            drawdown=self._float_or_none(data.get("drawdown")),
            turnover=self._float_or_none(data.get("turnover")),
            margin=self._float_or_none(data.get("margin")),
            checks_failed=self._float_or_none(data.get("checks_failed")),
            raw=data,
        )


class MockBrainClient(BrainClient):
    def __init__(self, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.rate_limiter = rate_limiter or RateLimiter(0.0)
        self.random = random.Random(23)
        self.results: Dict[str, SimulationMetrics] = {}
        self.last_login_mode = "mock"

    def login(self) -> None:
        return None

    def simulate(self, candidate: AlphaCandidate) -> SimulationHandle:
        self.rate_limiter.wait()
        simulation_id = hashlib.md5(candidate.expression.encode("utf-8")).hexdigest()[:12]
        base = sum(ord(char) for char in candidate.expression) % 100
        self.results[simulation_id] = SimulationMetrics(
            alpha_id=f"mock-{simulation_id}",
            status="COMPLETE",
            sharpe=round(0.7 + (base % 9) * 0.12, 4),
            fitness=round(0.5 + (base % 11) * 0.1, 4),
            returns=round(0.02 + (base % 8) * 0.01, 4),
            drawdown=round(0.01 + (base % 5) * 0.015, 4),
            turnover=round(0.1 + (base % 6) * 0.03, 4),
            margin=round(0.03 + (base % 7) * 0.01, 4),
            checks_failed=0,
            raw={"mode": "mock"},
        )
        return SimulationHandle(simulation_id=simulation_id, submitted_at=utc_now_iso(), metadata={"mode": "mock"})

    def poll(self, simulation_id: str) -> Dict[str, Any]:
        self.rate_limiter.wait()
        return {"status": "complete", "alpha": simulation_id, "simulation_id": simulation_id}

    def fetch_result(self, result_id: str) -> SimulationMetrics:
        self.rate_limiter.wait()
        return self.results[result_id]


def build_client(settings: Settings, rate_limiter: RateLimiter) -> BrainClient:
    mode = settings.client_mode.lower()
    if mode == "mock" or settings.dry_run:
        return MockBrainClient(rate_limiter)
    if mode == "requests":
        return RequestsBrainClient(settings, rate_limiter)
    raise ValueError(f"Unknown client mode: {settings.client_mode}. Use requests or mock.")
