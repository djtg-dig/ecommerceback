import json
from decimal import Decimal

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.inventory.models import InventoryItem


pytestmark = pytest.mark.django_db


def setup_pos():
    category, _ = ProductCategory.objects.get_or_create(
        code="POS", defaults={"name": "POS", "slug": "pos"}
    )
    business = Business.objects.create(name="POS shop")
    employee = CarriIdentity.objects.create(carri_subject="pos-employee")
    BusinessMember.objects.create(business=business, identity=employee, role="EMPLOYEE")
    client = APIClient()
    client.force_authenticate(user=employee)
    return category, business, employee, client


def product(category, business, name="Tea", **values):
    defaults = {"selling_price": Decimal("10.00"), "currency": "CDF", "attributes": {}}
    defaults.update(values)
    return Product.objects.create(business=business, category=category, name=name, **defaults)


def search(client, business, query, **params):
    return client.get(
        f"/api/v1/businesses/{business.public_id}/products/pos/search/",
        {"q": query, **params},
    )


def test_pos_product_stock_price_and_employee_access():
    category, business, _, client = setup_pos()
    item = product(category, business, barcode=" 111 ", internal_reference=" tea-1 ")
    InventoryItem.objects.create(business=business, product=item, quantity="5.000", reserved_quantity="2.000")

    response = search(client, business, "111")

    assert response.status_code == 200
    row = response.data["results"][0]
    assert row == {
        "type": "PRODUCT", "public_id": item.public_id, "product_public_id": item.public_id,
        "name": "Tea", "variant_label": None, "internal_reference": " tea-1 ",
        "barcode": " 111 ", "effective_price": "10.00", "currency": "CDF",
        "available_quantity": "3.000",
    }
    assert search(client, business, "  tea-1 ").data["results"][0]["public_id"] == item.public_id


def test_pos_variants_hide_parent_and_resolve_prices_and_stock():
    category, business, _, client = setup_pos()
    parent = product(category, business, name="Shirt", selling_price="20.00")
    inherited = ProductVariant.objects.create(product=parent, attributes={"size": "M"}, barcode="VAR-1")
    override = ProductVariant.objects.create(product=parent, attributes={"size": "L"}, selling_price="25.00", internal_reference="shirt-l")
    InventoryItem.objects.create(business=business, variant=inherited, quantity="1.000")

    assert search(client, business, parent.public_id).data["results"] == []
    first = search(client, business, "VAR-1").data["results"][0]
    second = search(client, business, "SHIRT-L").data["results"][0]
    assert first["type"] == "VARIANT" and first["effective_price"] == "20.00"
    assert first["available_quantity"] == "1.000" and first["variant_label"] == "size: M"
    assert second["effective_price"] == "25.00" and second["available_quantity"] == "0.000"


def test_pos_filters_inactive_and_reports_identifier_conflicts():
    category, business, _, client = setup_pos()
    inactive = product(category, business, name="Hidden", status="INACTIVE", barcode="HIDDEN")
    visible = product(category, business, barcode=" DUP ", internal_reference="sku-dup")
    other = product(category, business, name="Other")
    ProductVariant.objects.create(product=other, attributes={"size": "S"}, barcode="DUP")

    assert search(client, business, inactive.public_id).data["results"] == []
    conflict = search(client, business, "DUP")
    assert conflict.status_code == 409 and conflict.data["code"] == "pos_barcode_conflict"
    ProductVariant.objects.create(product=other, attributes={"size": "M"}, internal_reference=visible.internal_reference)
    sku_conflict = search(client, business, visible.internal_reference)
    assert sku_conflict.status_code == 409 and sku_conflict.data["code"] == "pos_sku_conflict"


def test_pos_excludes_archived_variant_and_suspended_member():
    category, business, employee, client = setup_pos()
    parent = product(category, business, name="Archived variant parent")
    archived = ProductVariant.objects.create(
        product=parent,
        attributes={"size": "M"},
        barcode="ARCHIVED-VARIANT",
        status="ARCHIVED",
    )

    assert search(client, business, archived.public_id).data["results"] == []
    text_results = search(client, business, "Archived variant parent").data["results"]
    assert [row["public_id"] for row in text_results] == [parent.public_id]

    membership = BusinessMember.objects.get(business=business, identity=employee)
    membership.status = BusinessMember.Status.SUSPENDED
    membership.save(update_fields=("status", "updated_at"))

    assert search(client, business, "anything").status_code == 404


def test_pos_text_pagination_validation_isolation_and_constant_queries():
    category, business, _, client = setup_pos()
    for index in range(5):
        product(category, business, name=f"Soap {index:02d}")
    with CaptureQueriesContext(connection) as small_queries:
        small_response = search(client, business, "Soap", page_size=50)

    for index in range(5, 105):
        product(category, business, name=f"Soap {index:02d}")
    with CaptureQueriesContext(connection) as large_queries:
        response = search(client, business, "Soap", page_size=50)

    foreign = Business.objects.create(name="Other")
    product(category, foreign, name="Soap foreign")

    assert small_response.status_code == 200
    assert response.status_code == 200
    assert small_response.data["count"] == 5
    assert response.data["count"] == 105 and len(response.data["results"]) == 50
    assert len(small_queries) == len(large_queries)
    assert len(large_queries) <= 9
    payload_size = len(json.dumps(response.data).encode("utf-8"))
    assert payload_size < 20_000
    assert search(client, business, " ").status_code == 400
    assert client.get(f"/api/v1/businesses/{foreign.public_id}/products/pos/search/", {"q": "Soap"}).status_code == 404
