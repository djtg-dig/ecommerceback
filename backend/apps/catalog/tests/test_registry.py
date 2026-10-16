"""Unit tests for the immutable, code-defined product registry."""

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalog.registry import (
    CATEGORY_REGISTRY,
    get_category,
    list_categories,
    validate_attributes,
    validate_registry,
)


EXPECTED_CATEGORIES = {
    "televisions",
    "smartphones",
    "feature_phones",
    "game_consoles",
    "tv_accessories",
    "laptops",
    "desktop_computers",
    "computer_accessories",
    "printers",
    "computer_components",
    "shoes",
    "clothing",
    "bags",
    "watches",
    "air_conditioners",
    "refrigerators",
    "freezers",
    "washing_machines",
    "fans",
    "furniture",
    "food",
    "construction_materials",
    "tools",
    "kitchenware",
    "hygiene_products",
    "school_supplies",
    "books",
    "toys",
    "sports_equipment",
    "automotive_parts",
    "agricultural_products",
    "other_products",
}


def test_registry_contains_all_expected_unique_categories():
    validate_registry()
    categories = list_categories()

    assert set(CATEGORY_REGISTRY) == EXPECTED_CATEGORIES
    assert categories == sorted(
        categories,
        key=lambda item: (item.parent, item.label.casefold(), item.code),
    )


def test_registry_public_contract_exposes_constraints_and_options():
    television = get_category("televisions").public(include_attributes=True)
    screen_size = next(item for item in television["attributes"] if item["code"] == "screen_size")
    technology = next(
        item for item in television["attributes"] if item["code"] == "display_technology"
    )

    assert television["parent"] == "electronics"
    assert screen_size == {
        "code": "screen_size",
        "label": "Taille de l’écran",
        "type": "decimal",
        "required": True,
        "unit": "inch",
        "options": [],
        "min_value": "1",
        "max_value": "200",
        "variant": False,
    }
    assert "OLED" in technology["options"]


def test_registry_attribute_validation_normalizes_supported_types():
    result = validate_attributes(
        "televisions",
        {
            "screen_size": 55,
            "smart_tv": True,
            "hdmi_ports": 3,
            "display_technology": "OLED",
        },
    )

    assert result == {
        "screen_size": "55",
        "smart_tv": True,
        "hdmi_ports": 3,
        "display_technology": "OLED",
    }


@pytest.mark.parametrize(
    ("code", "attributes"),
    [
        ("missing", {}),
        ("televisions", {}),
        ("televisions", {"screen_size": 0}),
        ("televisions", {"screen_size": 55, "smart_tv": "true"}),
        ("televisions", {"screen_size": 55, "unknown": "value"}),
        ("televisions", {"screen_size": 55, "display_technology": "CRT"}),
    ],
)
def test_registry_attribute_validation_rejects_invalid_payloads(code, attributes):
    with pytest.raises(ValidationError):
        validate_attributes(code, attributes)


def test_variant_attributes_are_validated_separately():
    assert validate_attributes("smartphones", {"storage": 256}, variant=True) == {
        "storage": 256
    }
    with pytest.raises(ValidationError, match="mauvais niveau|non autorisée"):
        validate_attributes("smartphones", {"storage": 256})


def test_registry_read_api_is_public_and_does_not_require_database_rows():
    client = APIClient()

    listing = client.get("/api/v1/product-categories/registry/")
    detail = client.get("/api/v1/product-categories/registry/televisions/")

    assert listing.status_code == 200
    assert {item["code"] for item in listing.json()} == EXPECTED_CATEGORIES
    assert detail.status_code == 200
    assert detail.json()["code"] == "televisions"
    assert any(item["code"] == "screen_size" for item in detail.json()["attributes"])
    assert client.get("/api/v1/product-categories/registry/missing/").status_code == 404
