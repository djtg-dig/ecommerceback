from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.businesses.models import Business
from apps.catalog.models import Product, ProductCategory, UnitOfMeasure


pytestmark = pytest.mark.django_db


@pytest.fixture
def public_catalog():
    unit, _ = UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Pièce", "symbol": "pcs", "category": "COUNT"})
    category = ProductCategory.objects.create(code="PUBLIC_CAT", name="Chaussures", slug="chaussures")
    shop = Business.objects.create(name="Boutique publique")
    private_shop = Business.objects.create(name="Boutique privée")
    visible = Product.objects.create(business=shop, category=category, name="Chaussure rouge", unit_of_measure=unit, selling_price=Decimal("10"), currency="CDF", attributes={}, is_public=True)
    Product.objects.create(business=shop, category=category, name="Privé", unit_of_measure=unit, selling_price=Decimal("5"), currency="CDF", attributes={})
    return shop, private_shop, visible


def test_public_catalog_is_opt_in_and_searchable(public_catalog):
    shop, _, visible = public_catalog
    client = APIClient()
    home = client.get("/api/v1/public/products/home/")
    assert home.status_code == 200 and [row["public_id"] for row in home.data["results"]] == [visible.public_id]
    assert client.get("/api/v1/public/products/search/", {"q": "ROUGE"}).data["count"] == 1
    assert client.get(f"/api/v1/public/products/{visible.public_id}/").data["business"] == shop.public_id
    suggestions = client.get("/api/v1/public/products/suggestions/", {"q": "chauss"})
    assert suggestions.status_code == 200 and any(item["type"] == "CATEGORY" for item in suggestions.data)


def test_public_catalog_never_returns_private_fields_or_inactive_products(public_catalog):
    _, _, visible = public_catalog
    visible.status = Product.Status.ARCHIVED
    visible.save()
    response = APIClient().get("/api/v1/public/products/search/")
    assert response.status_code == 200 and response.data["count"] == 0
    assert APIClient().get(f"/api/v1/public/products/{visible.public_id}/").status_code == 404
