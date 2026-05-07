from unittest.mock import Mock

from app.catalog import BrainCatalogSync


def test_catalog_builds_fields_by_dataset(settings):
    sync = BrainCatalogSync(settings, settings.fields_config)
    catalog = sync._build_catalog(
        data_fields=[
            {"id": "close", "dataset": {"id": "pv"}},
            {"id": "volume", "dataset": {"id": "pv"}},
            {"id": "eps", "datasetId": "fundamental"},
        ],
        datasets=[{"id": "pv"}, {"id": "fundamental"}],
        operators=[{"name": "rank"}],
    )

    assert catalog["metadata"]["field_count"] == 3
    assert catalog["fields_by_dataset"]["pv"] == ["close", "volume"]
    assert "eps" in catalog["field_ids"]
    assert "rank" in catalog["operator_ids"]


def test_catalog_extracts_items_from_common_api_shapes(settings):
    sync = BrainCatalogSync(settings, settings.fields_config)

    assert sync._extract_items([{"id": "x"}]) == [{"id": "x"}]
    assert sync._extract_items({"results": [{"id": "x"}]}) == [{"id": "x"}]
    assert sync._extract_items({"data": [{"id": "x"}]}) == [{"id": "x"}]
    assert sync._extract_total({"count": 12}) == 12
