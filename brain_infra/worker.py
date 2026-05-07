import datetime
import os
import pickle
import random
import time
from typing import Dict, List, Tuple

import requests
from requests.auth import HTTPBasicAuth

from brain_infra.alpha import Alpha, AlphaStage, DB_PATH, init_db


_SESSION_CACHE = os.path.join(DB_PATH, "session_cache.pkl")
TIMEOUT = 4
SIM_LIMIT = 3
API_BASE_URL = os.getenv("WQ_API_BASE_URL", "https://api.worldquantbrain.com")
API_LOGIN_PATH = os.getenv("WQ_API_LOGIN_PATH", "/authentication")
API_SIMULATE_PATH = os.getenv("WQ_API_SIMULATE_PATH", "/simulations")
AUTH_MODE = os.getenv("WQ_AUTH_MODE", "auto").lower()


def load_dotenv() -> None:
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


class BrainSession:
    def __init__(self) -> None:
        self._sess = None
        self.login()

    def login(self, force_relogin: bool = False) -> None:
        init_db()
        load_dotenv()
        if not force_relogin and os.path.exists(_SESSION_CACHE) and self._session_is_valid():
            with open(_SESSION_CACHE, "rb") as handle:
                self._sess = pickle.load(handle)
            return

        self._sess = requests.Session()
        username = os.getenv("WQ_USERNAME", "")
        password = os.getenv("WQ_PASSWORD", "")
        if not username or not password:
            raise ValueError("WQ_USERNAME and WQ_PASSWORD must be set in environment or .env.")

        login_url = f"{os.getenv('WQ_API_BASE_URL', API_BASE_URL)}{os.getenv('WQ_API_LOGIN_PATH', API_LOGIN_PATH)}"
        modes = self._auth_attempts()
        last_error = "login failed"
        for mode in modes:
            if mode == "basic":
                response = self._sess.post(
                    login_url,
                    auth=HTTPBasicAuth(username, password),
                    timeout=30,
                )
            elif mode == "json":
                response = self._sess.post(
                    login_url,
                    json={"username": username, "password": password},
                    timeout=30,
                )
            else:
                response = self._sess.post(
                    login_url,
                    data={"username": username, "password": password},
                    timeout=30,
                )
            if response.status_code < 400:
                break
            last_error = f"{mode}: {response.status_code} {response.text[:300]}"
        else:
            raise Exception(f"Authentication failed: {last_error}")

        with open(_SESSION_CACHE, "wb") as handle:
            pickle.dump(self._sess, handle)

    @staticmethod
    def _auth_attempts() -> List[str]:
        mode = os.getenv("WQ_AUTH_MODE", AUTH_MODE).lower()
        if mode == "auto":
            return ["basic", "json", "form"]
        if mode not in {"basic", "json", "form"}:
            raise ValueError(f"Unknown WQ_AUTH_MODE: {mode}")
        return [mode]

    def _session_is_valid(self) -> bool:
        if not os.path.exists(_SESSION_CACHE):
            return False
        return datetime.datetime.now() - datetime.datetime.fromtimestamp(
            os.path.getmtime(_SESSION_CACHE)
        ) < datetime.timedelta(hours=TIMEOUT)

    def _request(self, method: str, *args, **kwargs):
        response = getattr(self._sess, method)(*args, **kwargs)
        if response.status_code == 401:
            self.login(force_relogin=True)
            response = getattr(self._sess, method)(*args, **kwargs)
        if response.status_code in (200, 201):
            return response
        raise Exception(f"Unexpected status code {response.status_code}: {response.headers}")

    def get(self, *args, **kwargs):
        return self._request("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self._request("post", *args, **kwargs)

    def patch(self, *args, **kwargs):
        return self._request("patch", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._request("delete", *args, **kwargs)


class Worker:
    def __init__(self) -> None:
        self.sess = BrainSession()

    @staticmethod
    def get_pending_filepaths(running_filepaths: List[str]) -> List[str]:
        init_db()
        pending_paths = []
        for filename in os.listdir(AlphaStage.PENDING.value):
            full_path = os.path.join(AlphaStage.PENDING.value, filename)
            if not filename.endswith(".json"):
                continue
            if filename.startswith("tmp"):
                continue
            if full_path in running_filepaths:
                continue
            pending_paths.append(full_path)
        return pending_paths

    def _post_payload(self, alpha: Alpha) -> Tuple[bool, str]:
        response = self.sess.post(
            f"{os.getenv('WQ_API_BASE_URL', API_BASE_URL)}{os.getenv('WQ_API_SIMULATE_PATH', API_SIMULATE_PATH)}",
            json=alpha.payload,
        )
        location = response.headers.get("Location", "")
        if response.status_code in (200, 201) and location:
            return True, location
        return False, ""

    def _get_status(self, location_url: str) -> Tuple[bool, str, str]:
        response = self.sess.get(location_url)
        if response.status_code not in (200, 201):
            return False, "0", ""
        retry_after = response.headers.get("Retry-After", "0")
        response_json = response.json()
        if retry_after == "0" and "alpha" not in response_json:
            return False, "0", ""
        if retry_after == "0" and "alpha" in response_json:
            return True, "0", response_json["alpha"]
        return True, retry_after, ""

    def _get_result(self, alpha_id: str) -> dict:
        response = self.sess.get(f"https://api.worldquantbrain.com/alphas/{alpha_id}")
        return response.json()

    def run(self) -> None:
        init_db()
        running_simulations: Dict[str, str] = {}
        try:
            while True:
                available_slots = max(0, SIM_LIMIT - len(running_simulations))
                pending_filepaths = self.get_pending_filepaths(list(running_simulations.keys()))
                for filepath in pending_filepaths[:available_slots]:
                    alpha = Alpha.load(filepath)
                    try:
                        ok, location_url = self._post_payload(alpha)
                    except Exception:
                        ok, location_url = False, ""
                    if ok:
                        running_simulations[filepath] = location_url
                        time.sleep(1)
                    else:
                        alpha.update_stage(AlphaStage.ERROR)

                for filepath, location_url in list(running_simulations.items()):
                    try:
                        ok, retry_after, alpha_id = self._get_status(location_url)
                    except Exception:
                        ok, retry_after, alpha_id = False, "0", ""
                    if not ok:
                        alpha = Alpha.load(filepath)
                        alpha.update_stage(AlphaStage.ERROR)
                        del running_simulations[filepath]
                        break
                    if retry_after == "0" and alpha_id:
                        alpha = Alpha.load(filepath)
                        alpha.result.update(self._get_result(alpha_id))
                        alpha.update_stage(AlphaStage.COMPLETE)
                        del running_simulations[filepath]
                        break
                    time.sleep(float(retry_after))

                if not running_simulations:
                    time.sleep(5)
        finally:
            for location_url in running_simulations.values():
                try:
                    self.sess.delete(location_url)
                except Exception:
                    pass


class FakeWorker(Worker):
    def __init__(self) -> None:
        self.sess = requests.Session()

    def _post_payload(self, alpha: Alpha) -> Tuple[bool, str]:
        return True, "https://fake.url"

    def _get_status(self, location_url: str) -> Tuple[bool, str, str]:
        return True, "0", "fake_id"

    def _get_result(self, alpha_id: str) -> dict:
        return {
            "is": {
                "sharpe": random.uniform(-0.6, 2.4),
                "turnover": random.uniform(0.0, 1.0),
                "fitness": 0.0,
                "returns": 0.0,
                "drawdown": 0.0,
                "margin": 0.0,
            },
            "startDate": "2012-07-15",
        }
