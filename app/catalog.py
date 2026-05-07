from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json

from app.api import RateLimiter, RequestsBrainClient
from app.config import Settings


DEFAULT_FIELD_GROUPS = {
    "price_fields": ["close", "open", "high", "low", "vwap", "returns"],
    "volume_fields": ["volume", "adv20", "adv60"],
    "fundamental_fields": ["eps", "operating_margin", "sales", "book_value", "cashflow"],
    "group_fields": ["sector", "industry", "subindustry"],
    "windows": [5, 10, 20, 40, 60, 120],
    "decays": [3, 5, 10],
    "wrappers": ["rank", "zscore", "ts_rank", "ts_decay_linear"],
}


@dataclass
class BrainCatalogSync:
    settings: Settings
    output_path: Path
    limit: int = 50

    def run(self, *, include_operators: bool = True) -> Path:
        client = RequestsBrainClient(self.settings, RateLimiter(self.settings.rate_limit_seconds))
        client.login()
        datasets = self._fetch_datasets(client)
        data_fields = self._fetch_all_data_fields(client, datasets)
        operators = self._fetch_operators(client) if include_operators else []
        catalog = self._build_catalog(data_fields, datasets, operators)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
        return self.output_path

    def _fetch_datasets(self, client: RequestsBrainClient) -> List[dict]:
        for path in ("/data-sets", "/datasets"):
            response = self._get(client, path, params=self._base_params())
            if response.status_code == 404:
                continue
            response.raise_for_status()
            return self._extract_items(response.json())
        return []

    def _fetch_all_data_fields(self, client: RequestsBrainClient, datasets: List[dict]) -> List[dict]:
        seen: set[str] = set()
        fields: List[dict] = []
        dataset_ids = [str(item.get("id") or item.get("name")) for item in datasets if item.get("id") or item.get("name")]
        if not dataset_ids:
            fields.extend(self._fetch_data_fields_page_loop(client, None))
        else:
            for dataset_id in dataset_ids:
                fields.extend(self._fetch_data_fields_page_loop(client, dataset_id))
        deduped: List[dict] = []
        for item in fields:
            field_id = str(item.get("id") or item.get("name") or item.get("field") or "")
            if not field_id or field_id in seen:
                continue
            seen.add(field_id)
            deduped.append(item)
        return sorted(deduped, key=lambda item: str(item.get("id") or item.get("name") or ""))

    def _fetch_data_fields_page_loop(self, client: RequestsBrainClient, dataset_id: Optional[str]) -> List[dict]:
        offset = 0
        collected: List[dict] = []
        while True:
            params = {**self._base_params(), "limit": self.limit, "offset": offset}
            if dataset_id:
                params["dataset.id"] = dataset_id
            response = self._get(client, "/data-fields", params=params)
            response.raise_for_status()
            payload = response.json()
            items = self._extract_items(payload)
            if not items:
                break
            collected.extend(items)
            total = self._extract_total(payload)
            offset += len(items)
            if total is not None and offset >= total:
                break
            if len(items) < self.limit:
                break
        return collected

    def _fetch_operators(self, client: RequestsBrainClient) -> List[dict]:
        response = self._get(client, "/operators", params={"limit": 1000})
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return self._extract_items(response.json())

    def _get(self, client: RequestsBrainClient, path: str, params: Optional[Dict[str, Any]] = None):
        if not client.logged_in:
            client.login()
        client.rate_limiter.wait()
        response = client.session.get(client.settings.api_base_url + path, params=params or {}, timeout=30)
        if response.status_code in {401, 403}:
            client.logged_in = False
            client.login()
            response = client.session.get(client.settings.api_base_url + path, params=params or {}, timeout=30)
        return response

    def _base_params(self) -> Dict[str, Any]:
        return {
            "instrumentType": self.settings.instrument_type,
            "region": self.settings.region,
            "universe": self.settings.universe,
            "delay": self.settings.delay,
        }

    def _build_catalog(self, data_fields: List[dict], datasets: List[dict], operators: List[dict]) -> Dict[str, Any]:
        field_ids = [str(item.get("id") or item.get("name")) for item in data_fields if item.get("id") or item.get("name")]
        fields_by_dataset: Dict[str, List[str]] = {}
        for item in data_fields:
            dataset = item.get("dataset")
            if isinstance(dataset, dict):
                dataset_id = str(dataset.get("id") or dataset.get("name") or "unknown")
            else:
                dataset_id = str(item.get("datasetId") or item.get("dataset_id") or "unknown")
            field_id = str(item.get("id") or item.get("name") or "")
            if field_id:
                fields_by_dataset.setdefault(dataset_id, []).append(field_id)

        catalog: Dict[str, Any] = {
            **DEFAULT_FIELD_GROUPS,
            "metadata": {
                "source": "WorldQuant BRAIN API",
                "instrument_type": self.settings.instrument_type,
                "region": self.settings.region,
                "universe": self.settings.universe,
                "delay": self.settings.delay,
                "field_count": len(field_ids),
                "dataset_count": len(datasets),
                "operator_count": len(operators),
            },
            "data_fields": data_fields,
            "field_ids": field_ids,
            "fields_by_dataset": {key: sorted(values) for key, values in sorted(fields_by_dataset.items())},
            "datasets": datasets,
            "operators": operators,
            "operator_ids": [
                str(item.get("name") or item.get("id"))
                for item in operators
                if item.get("name") or item.get("id")
            ],
        }
        return catalog

    @staticmethod
    def _extract_items(payload: Any) -> List[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("results", "data", "items"):
            items = payload.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_total(payload: Any) -> Optional[int]:
        if not isinstance(payload, dict):
            return None
        for key in ("count", "total", "totalCount"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        return None
