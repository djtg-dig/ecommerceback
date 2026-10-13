from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import (
    apply_stock_movement,
)


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def inventory_context():
    category = ProductCategory.objects.create(
        code="INV_ADVANCED",
        name="Inventory advanced",
        slug="inventory-advanced",
    )
    business = Business.objects.create(name="Inventory advanced")
    other = Business.objects.create(name="Other inventory")
    owner = CarriIdentity.objects.create(carri_subject="advanced-inventory-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    product = Product.objects.create(
        business=business,
        category=category,
        name="Tracked product",
        internal_reference="SKU-TRACKED",
        selling_price="10",
        cost_price="4",
        currency="CDF",
    )
    item = InventoryItem.objects.create(
        business=business,
        product=product,
        low_stock_threshold="3.000",
    )
    return business, other, owner, product, item


def api(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def test_manual_idempotency_replays_once_and_rejects_another_intent(inventory_context):
    business, other, owner, product, item = inventory_context
    endpoint = f"/api/v1/businesses/{business.public_id}/inventory/{item.public_id}/movements/"
    headers = {"HTTP_IDEMPOTENCY_KEY": "manual-stock-key"}

    created = api(owner).post(endpoint, {"type": "IN", "quantity": "5.000"}, format="json", **headers)
    replayed = api(owner).post(endpoint, {"type": "IN", "quantity": "5.000"}, format="json", **headers)
    conflict = api(owner).post(endpoint, {"type": "IN", "quantity": "6.000"}, format="json", **headers)

    item.refresh_from_db()
    assert created.status_code == 201
    assert replayed.status_code == 200
    assert replayed.data["public_id"] == created.data["public_id"]
    assert conflict.status_code == 409
    assert item.quantity == Decimal("5.000")
    assert StockMovement.objects.filter(inventory_item=item).count() == 1


def test_summary_filters_history_and_tenant_isolation(inventory_context):
    business, other, owner, product, item = inventory_context
    apply_stock_movement(
        inventory_item=item,
        movement_type=StockMovement.Type.IN,
        performed_by=owner,
        quantity=Decimal("2.000"),
        reason="Counted",
        idempotency_key="summary-movement",
    )

    summary = api(owner).get(f"/api/v1/businesses/{business.public_id}/inventory/summary/")
    history = api(owner).get(
        f"/api/v1/businesses/{business.public_id}/inventory/movements/",
        {"product": product.public_id, "type": "IN", "origin": ""},
    )
    isolated = api(owner).get(f"/api/v1/businesses/{other.public_id}/inventory/summary/")

    assert summary.status_code == 200
    assert summary.data["tracked_products"] == 1
    assert summary.data["in_stock"] == 1
    assert summary.data["low_stock"] == 1
    assert summary.data["total_available_quantity"] == "2.000"
    assert summary.data["recent_movements"][0]["item_name"] == product.name
    assert history.status_code == 200
    assert history.data["count"] == 1
    assert history.data["results"][0]["reference_type"] is None
    assert isolated.status_code == 404


def test_concurrent_outputs_never_lose_updates_or_go_negative(inventory_context):
    business, other, owner, product, item = inventory_context
    apply_stock_movement(
        inventory_item=item,
        movement_type=StockMovement.Type.IN,
        performed_by=owner,
        quantity=Decimal("10.000"),
    )

    def remove_once(key):
        close_old_connections()
        try:
            movement = apply_stock_movement(
                inventory_item=item,
                movement_type=StockMovement.Type.OUT,
                performed_by=owner,
                quantity=Decimal("7.000"),
                idempotency_key=key,
            )
            return movement.public_id
        except ValidationError:
            return "refused"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(remove_once, ("concurrent-a", "concurrent-b")))

    item.refresh_from_db()
    assert results.count("refused") == 1
    assert item.quantity == Decimal("3.000")
    assert StockMovement.objects.filter(
        inventory_item=item,
        movement_type=StockMovement.Type.OUT,
    ).count() == 1
