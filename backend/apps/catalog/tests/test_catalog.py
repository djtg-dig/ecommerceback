"""Tests for taxonomy validation, inheritance and public read APIs."""

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalog.models import AttributeDefinition, AttributeOption, ProductCategory
from apps.catalog.services import effective_attributes

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def taxonomy():
    root = ProductCategory.objects.create(code="ROOT", name="Root", slug="root")
    child = ProductCategory.objects.create(code="CHILD", name="Child", slug="child", parent=root)
    leaf = ProductCategory.objects.create(
        code="LEAF", name="Leaf", slug="leaf", parent=child, product_type_key="LEAF_TYPE"
    )
    return root, child, leaf


def test_category_levels_are_limited_to_three(taxonomy):
    _, _, leaf = taxonomy
    with pytest.raises(ValidationError, match="trois niveaux"):
        ProductCategory.objects.create(code="TOO_DEEP", name="Too deep", slug="too-deep", parent=leaf)


def test_category_rejects_self_parent_and_indirect_cycle(taxonomy):
    root, child, _ = taxonomy
    root.parent = root
    with pytest.raises(ValidationError, match="propre parent"):
        root.save()

    root.parent = child
    with pytest.raises(ValidationError, match="cycle"):
        root.save()


def test_attribute_code_cannot_shadow_ancestor(taxonomy):
    root, _, leaf = taxonomy
    AttributeDefinition.objects.create(category=root, code="brand", name="Marque", data_type="text")
    with pytest.raises(ValidationError, match="ancêtre"):
        AttributeDefinition.objects.create(category=leaf, code="brand", name="Brand", data_type="text")


def test_effective_attributes_inherit_active_options(taxonomy):
    root, _, leaf = taxonomy
    brand = AttributeDefinition.objects.create(
        category=root, code="brand", name="Marque", data_type="choice", sort_order=2
    )
    AttributeOption.objects.create(attribute_definition=brand, value="acme", label="Acme")
    AttributeOption.objects.create(attribute_definition=brand, value="legacy", label="Legacy", is_active=False)
    AttributeDefinition.objects.create(
        category=leaf, code="screen_size", name="Taille écran", data_type="decimal", unit="in", sort_order=1
    )

    resolved = effective_attributes(leaf)
    assert [(item.definition.code, item.inherited_from.code) for item in resolved] == [
        ("brand", "ROOT"),
        ("screen_size", "LEAF"),
    ]


def test_public_categories_are_flat_and_hide_inactive(client, taxonomy):
    root, child, leaf = taxonomy
    ProductCategory.objects.create(code="HIDDEN", name="Hidden", slug="hidden", is_active=False)

    response = client.get("/api/v1/product-categories/")

    assert response.status_code == 200
    records = {item["code"]: item for item in response.json()}
    assert set(records) >= {root.code, child.code, leaf.code}
    assert "HIDDEN" not in records
    assert records[leaf.code]["parent_code"] == child.code
    assert records[leaf.code]["level"] == 3
    assert records[leaf.code]["product_type_key"] == "LEAF_TYPE"


def test_public_effective_attributes_are_inherited_and_filter_options(client, taxonomy):
    root, _, leaf = taxonomy
    color = AttributeDefinition.objects.create(
        category=root, code="color", name="Couleur", data_type="choice", is_filterable=True
    )
    AttributeOption.objects.create(attribute_definition=color, value="red", label="Rouge")
    AttributeOption.objects.create(attribute_definition=color, value="old", label="Ancien", is_active=False)
    AttributeDefinition.objects.create(category=root, code="retired", name="Retired", data_type="text", is_active=False)

    response = client.get(f"/api/v1/product-categories/{leaf.code}/attributes/")

    assert response.status_code == 200
    assert response.json() == [
        {
            "code": "color", "name": "Couleur", "data_type": "choice", "unit": "",
            "is_required": False, "is_filterable": True, "is_variant_axis": False,
            "sort_order": 0, "inherited_from": "ROOT",
            "options": [{"value": "red", "label": "Rouge", "sort_order": 0}],
        }
    ]


def test_inactive_or_unknown_category_attributes_are_not_public(client, taxonomy):
    _, _, leaf = taxonomy
    leaf.is_active = False
    leaf.save()

    assert client.get(f"/api/v1/product-categories/{leaf.code}/attributes/").status_code == 404
    assert client.get("/api/v1/product-categories/MISSING/attributes/").status_code == 404
