"""Inventory API and atomic stock-service tests on PostgreSQL."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup():
    category = ProductCategory.objects.create(code="INV_CAT", name="Inventory", slug="inventory")
    business = Business.objects.create(name="Main")
    other = Business.objects.create(name="Other")
    owner = CarriIdentity.objects.create(carri_subject="inventory-owner")
    manager = CarriIdentity.objects.create(carri_subject="inventory-manager")
    employee = CarriIdentity.objects.create(carri_subject="inventory-employee")
    outsider = CarriIdentity.objects.create(carri_subject="inventory-outsider")
    owner_member = BusinessMember.objects.create(
        business=business, identity=owner, role="OWNER"
    )
    manager_member = BusinessMember.objects.create(
        business=business, identity=manager, role="MANAGER"
    )
    employee_member = BusinessMember.objects.create(
        business=business, identity=employee, role="EMPLOYEE"
    )
    grant_permission(
        owner_member,
        manager_member,
        BusinessMemberPermission.Permission.MANAGE_INVENTORY,
    )
    grant_permission(
        owner_member,
        employee_member,
        BusinessMemberPermission.Permission.VIEW_INVENTORY,
    )
    product = Product.objects.create(business=business, category=category, name="Simple", selling_price="1", currency="CDF", attributes={})
    other_product = Product.objects.create(business=other, category=category, name="Other", selling_price="1", currency="CDF", attributes={})
    return business, other, owner, manager, employee, outsider, product, other_product


def client(user):
    value = APIClient(); value.force_authenticate(user=user); return value


def create_item(user, business, **payload):
    response = client(user).post(f"/api/v1/businesses/{business.public_id}/inventory/", payload, format="json")
    assert response.status_code == 201, response.data
    return response.data


def test_inventory_item_creation_permissions_and_simple_invariants(setup):
    business, _, owner, manager, employee, outsider, product, _ = setup
    first = create_item(owner, business, product=product.public_id, low_stock_threshold="5.000")
    assert first["public_id"].startswith("IV") and first["quantity"] == "0.000"
    assert first["reserved_quantity"] == "0.000" and first["available_quantity"] == "0.000" and first["is_low_stock"] is True
    assert client(owner).post(f"/api/v1/businesses/{business.public_id}/inventory/", {"product": product.public_id}, format="json").status_code == 400
    assert client(employee).post(f"/api/v1/businesses/{business.public_id}/inventory/", {"product": product.public_id}, format="json").status_code == 403
    assert client(employee).get(f"/api/v1/businesses/{business.public_id}/inventory/").status_code == 200
    assert client(outsider).get(f"/api/v1/businesses/{business.public_id}/inventory/").status_code == 404
    assert client(manager).post(f"/api/v1/businesses/{business.public_id}/inventory/", {"product": product.public_id}, format="json").status_code == 400


def test_variant_inventory_and_product_variant_rule(setup):
    business, _, owner, _, _, _, product, _ = setup
    variant = ProductVariant.objects.create(product=product, attributes={}, selling_price=None, cost_price=None)
    assert client(owner).post(f"/api/v1/businesses/{business.public_id}/inventory/", {"product": product.public_id}, format="json").status_code == 400
    item = create_item(owner, business, variant=variant.public_id)
    assert item["variant"] == variant.public_id and item["product"] is None
    assert client(owner).post(f"/api/v1/businesses/{business.public_id}/inventory/", {}, format="json").status_code == 400
    assert client(owner).post(f"/api/v1/businesses/{business.public_id}/inventory/", {"product": product.public_id, "variant": variant.public_id}, format="json").status_code == 400


def test_cross_business_and_archived_targets_are_refused(setup):
    business, _, owner, _, _, _, product, other_product = setup
    endpoint = f"/api/v1/businesses/{business.public_id}/inventory/"
    assert client(owner).post(endpoint, {"product": other_product.public_id}, format="json").status_code == 400
    product.status = "ARCHIVED"; product.save()
    assert client(owner).post(endpoint, {"product": product.public_id}, format="json").status_code == 400


def test_manual_movements_and_history_are_atomic(setup):
    business, _, owner, manager, employee, _, product, _ = setup
    item_data = create_item(owner, business, product=product.public_id)
    endpoint = f"/api/v1/businesses/{business.public_id}/inventory/{item_data['public_id']}/movements/"
    received = client(owner).post(endpoint, {"type": "IN", "quantity": "10.000", "reason": "Initial"}, format="json")
    assert received.status_code == 201 and received.data["quantity_before"] == "0.000" and received.data["quantity_after"] == "10.000"
    out = client(manager).post(endpoint, {"type": "OUT", "quantity": "3.000"}, format="json")
    assert out.status_code == 201 and out.data["quantity"] == "-3.000" and out.data["quantity_after"] == "7.000"
    adjusted = client(owner).post(endpoint, {"type": "ADJUSTMENT", "target_quantity": "12.000"}, format="json")
    assert adjusted.status_code == 201 and adjusted.data["quantity"] == "5.000" and adjusted.data["quantity_after"] == "12.000"
    assert client(owner).post(endpoint, {"type": "OUT", "quantity": "13.000"}, format="json").status_code == 400
    assert client(owner).post(endpoint, {"type": "SALE", "quantity": "1.000"}, format="json").status_code == 400
    assert client(employee).post(endpoint, {"type": "IN", "quantity": "1.000"}, format="json").status_code == 403
    assert client(employee).get(endpoint).status_code == 200
    movement = StockMovement.objects.get(public_id=received.data["public_id"])
    assert movement.performed_by == owner
    with pytest.raises(ValidationError, match="immuable"):
        movement.reason = "rewrite"; movement.save()


def test_service_rejects_invalid_quantities_without_changing_balance(setup):
    business, _, owner, _, _, _, product, _ = setup
    item = InventoryItem.objects.create(business=business, product=product)
    with pytest.raises(ValidationError):
        apply_stock_movement(inventory_item=item, movement_type="IN", performed_by=owner, quantity=Decimal("0"))
    assert InventoryItem.objects.get(pk=item.pk).quantity == Decimal("0.000")
    with pytest.raises(ValidationError):
        apply_stock_movement(inventory_item=item, movement_type="ADJUSTMENT", performed_by=owner, target_quantity=Decimal("-1"))
    assert InventoryItem.objects.get(pk=item.pk).quantity == Decimal("0.000")


def test_variant_creation_is_refused_after_product_inventory_exists(setup):
    business, _, owner, _, _, _, product, _ = setup
    create_item(owner, business, product=product.public_id)
    endpoint = f"/api/v1/businesses/{business.public_id}/products/{product.public_id}/variants/"
    response = client(owner).post(endpoint, {"attributes": {}}, format="json")
    assert response.status_code == 400


def test_archived_product_rejects_new_movements(setup):
    business, _, owner, _, _, _, product, _ = setup
    item = create_item(owner, business, product=product.public_id)
    product.status = "ARCHIVED"; product.save()
    endpoint = f"/api/v1/businesses/{business.public_id}/inventory/{item['public_id']}/movements/"
    assert client(owner).post(endpoint, {"type": "IN", "quantity": "1.000"}, format="json").status_code == 400
