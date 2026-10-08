"""Regression coverage for immutable historical costs on completed sales."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import complete


pytestmark = pytest.mark.django_db


def sale_context(*, cost_price=Decimal("7.50")):
    category = ProductCategory.objects.create(
        code="SALE_SNAPSHOT",
        name="Sale snapshot",
        slug="sale-snapshot",
    )
    business = Business.objects.create(name="Sale snapshot business")
    employee = CarriIdentity.objects.create(carri_subject="sale-snapshot-employee")
    member = BusinessMember.objects.create(
        business=business,
        identity=employee,
        role="EMPLOYEE",
    )
    BusinessMemberPermission.objects.create(
        member=member,
        permission=BusinessMemberPermission.Permission.USE_POS,
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Snapshot product",
        selling_price=Decimal("20.00"),
        cost_price=cost_price,
        currency="CDF",
        attributes={},
    )
    inventory = InventoryItem.objects.create(business=business, product=product)
    apply_stock_movement(
        inventory_item=inventory,
        movement_type=StockMovement.Type.IN,
        performed_by=employee,
        quantity=Decimal("10.000"),
    )
    customer = Customer.objects.create(business=business, name="Snapshot customer")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency=business.primary_currency,
        created_by=employee,
    )
    line = SaleLine.objects.create(
        sale=sale,
        product=product,
        quantity=Decimal("2.000"),
        unit_price=Decimal("20.00"),
    )
    return business, employee, product, inventory, sale, line


def test_draft_sale_line_may_have_no_historical_cost_snapshot():
    _, _, _, _, sale, line = sale_context()

    assert sale.status == Sale.Status.DRAFT
    assert line.unit_cost_snapshot is None


def test_complete_freezes_product_cost_snapshot_and_later_price_changes_do_not_affect_it():
    _, employee, product, _, sale, line = sale_context()

    complete(sale, employee, Decimal("40.00"), "CASH")
    line.refresh_from_db()
    sale.refresh_from_db()

    assert sale.status == Sale.Status.COMPLETED
    assert line.unit_cost_snapshot == Decimal("7.50")

    product.cost_price = Decimal("12.00")
    product.save(update_fields=("cost_price", "updated_at"))
    line.refresh_from_db()

    assert line.unit_cost_snapshot == Decimal("7.50")


def test_complete_freezes_variant_cost_snapshot_and_later_price_changes_do_not_affect_it():
    business, employee, product, _, _, _ = sale_context()
    variant = ProductVariant.objects.create(
        product=product,
        attributes={},
        cost_price=Decimal("9.25"),
    )
    inventory = InventoryItem.objects.create(business=business, variant=variant)
    apply_stock_movement(
        inventory_item=inventory,
        movement_type=StockMovement.Type.IN,
        performed_by=employee,
        quantity=Decimal("10.000"),
    )
    sale = Sale.objects.create(
        business=business,
        customer=Customer.objects.create(business=business, name="Variant customer"),
        currency=business.primary_currency,
        created_by=employee,
    )
    line = SaleLine.objects.create(
        sale=sale,
        variant=variant,
        quantity=Decimal("1.000"),
        unit_price=Decimal("20.00"),
    )

    complete(sale, employee, Decimal("20.00"), "CASH")
    line.refresh_from_db()
    assert line.unit_cost_snapshot == Decimal("9.25")

    variant.cost_price = Decimal("15.00")
    variant.save(update_fields=("cost_price", "updated_at"))
    line.refresh_from_db()

    assert line.unit_cost_snapshot == Decimal("9.25")


def test_complete_rejects_missing_historical_cost_and_keeps_sale_draft():
    _, employee, _, inventory, sale, line = sale_context(cost_price=None)

    with pytest.raises(ValidationError, match="historical unit cost"):
        complete(sale, employee, Decimal("40.00"), "CASH")

    sale.refresh_from_db()
    line.refresh_from_db()
    inventory.refresh_from_db()
    assert sale.status == Sale.Status.DRAFT
    assert line.unit_cost_snapshot is None
    assert inventory.quantity == Decimal("10.000")
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.Type.SALE,
        reference_id=line.public_id,
    ).exists()


def test_finalization_failure_rolls_back_snapshot_and_inventory_effects():
    _, employee, _, inventory, sale, line = sale_context()

    with patch(
        "apps.sales.services.apply_stock_movement",
        side_effect=RuntimeError("inventory unavailable"),
    ):
        with pytest.raises(RuntimeError, match="inventory unavailable"):
            complete(sale, employee, Decimal("40.00"), "CASH")

    sale.refresh_from_db()
    line.refresh_from_db()
    inventory.refresh_from_db()
    assert sale.status == Sale.Status.DRAFT
    assert line.unit_cost_snapshot is None
    assert inventory.quantity == Decimal("10.000")
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.Type.SALE,
        reference_id=line.public_id,
    ).exists()


def test_completed_sale_lines_cannot_be_changed_through_normal_api_routes():
    business, employee, _, _, sale, line = sale_context()
    complete(sale, employee, Decimal("40.00"), "CASH")

    client = APIClient()
    client.force_authenticate(user=employee)
    lines_url = f"/api/v1/businesses/{business.public_id}/sales/{sale.public_id}/lines/"
    sale_url = f"/api/v1/businesses/{business.public_id}/sales/{sale.public_id}/"

    assert client.post(
        lines_url,
        {"product": line.product.public_id, "quantity": "1.000"},
        format="json",
    ).status_code == 400
    assert client.patch(sale_url, {"reference": "changed"}, format="json").status_code == 400

    line.refresh_from_db()
    assert line.unit_cost_snapshot == Decimal("7.50")
