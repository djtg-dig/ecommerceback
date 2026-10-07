from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import cancel, complete


pytestmark = pytest.mark.django_db


def make_context(suffix):
    business = Business.objects.create(name=f"Reports {suffix}")
    owner = CarriIdentity.objects.create(carri_subject=f"reports-owner-{suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"reports-manager-{suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"reports-employee-{suffix}")
    for identity, role in ((owner, "OWNER"), (manager, "MANAGER"), (employee, "EMPLOYEE")):
        BusinessMember.objects.create(business=business, identity=identity, role=role)
    category, _ = ProductCategory.objects.get_or_create(code="REPORTS", defaults={"name": "Reports", "slug": "reports"})
    return business, owner, manager, employee, category


def add_product(business, category, name, price, cost):
    product = Product.objects.create(business=business, category=category, name=name, selling_price=price, cost_price=cost, currency="CDF", attributes={})
    inventory = InventoryItem.objects.create(business=business, product=product)
    return product, inventory


def sell(business, owner, product=None, variant=None, price=Decimal("100"), quantity=Decimal("1")):
    target = variant or product
    inventory, _ = InventoryItem.objects.get_or_create(business=business, **({"variant": variant} if variant else {"product": product}))
    if inventory.quantity < quantity:
        apply_stock_movement(inventory_item=inventory, movement_type=StockMovement.Type.IN, performed_by=owner, quantity=Decimal("20"))
    sale = Sale.objects.create(business=business, customer=Customer.objects.create(business=business, name=f"Customer {Sale.objects.count()}"), currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=sale, product=product, variant=variant, quantity=quantity, unit_price=price)
    complete(sale, owner, price * quantity, "CASH")
    return sale


def api(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def test_sales_report_empty_permissions_periods_and_invalid_parameters():
    business, owner, manager, employee, _ = make_context("sales-empty")
    url = f"/api/v1/businesses/{business.public_id}/reports/sales/"
    for identity in (owner, manager):
        response = api(identity).get(url)
        assert response.status_code == 200
        assert response.data["totals"] == {"revenue": Decimal("0"), "sales_count": 0}
    assert api(employee).get(url).status_code == 404
    assert api(owner).get(url, {"group_by": "year"}).status_code == 400
    assert api(owner).get(url, {"period": "bad"}).status_code == 400
    assert api(owner).get(url, {"date_from": "2026-02-02"}).status_code == 400
    assert api(owner).get(url, {"date_from": "2026-02-02", "date_to": "2026-02-01"}).status_code == 400


def test_sales_report_series_excludes_non_completed_and_counts_sales_once():
    business, owner, _, _, category = make_context("sales-series")
    product, _ = add_product(business, category, "Product", Decimal("100"), Decimal("60"))
    sale = sell(business, owner, product, price=Decimal("100"))
    SaleLine.objects.create(sale=sale, product=Product.objects.create(business=business, category=category, name="Second", selling_price=Decimal("50"), cost_price=Decimal("20"), currency="CDF", attributes={}), quantity=Decimal("1"), unit_price=Decimal("50"))
    sale.refresh_from_db()
    old = sell(business, owner, product)
    old.completed_at = timezone.now() - timedelta(days=40)
    old.save(update_fields=("completed_at", "updated_at"))
    draft = Sale.objects.create(business=business, currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=draft, product=product, quantity=Decimal("1"), unit_price=Decimal("999"))
    response = api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/sales/", {"period": "last_30_days", "group_by": "day"})
    assert response.data["totals"] == {"revenue": Decimal("150"), "sales_count": 1}
    assert len(response.data["series"]) == 1
    for group_by in ("week", "month"):
        assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/sales/", {"period": "last_30_days", "group_by": group_by}).status_code == 200
    assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/sales/", {"date_from": timezone.localdate().isoformat(), "date_to": timezone.localdate().isoformat()}).data["totals"]["sales_count"] == 1


def test_product_report_groups_variants_uses_snapshots_orders_and_limits():
    business, owner, _, employee, category = make_context("products")
    product, _ = add_product(business, category, "Parent", Decimal("100"), Decimal("60"))
    sell(business, owner, product=product, price=Decimal("100"), quantity=Decimal("1"))
    variant_a = ProductVariant.objects.create(product=product, attributes={}, cost_price=Decimal("50"))
    variant_b = ProductVariant.objects.create(product=product, attributes={"x": "b"}, cost_price=Decimal("40"))
    sell(business, owner, variant=variant_a, price=Decimal("120"), quantity=Decimal("1"))
    sell(business, owner, variant=variant_b, price=Decimal("80"), quantity=Decimal("1"))
    old = sell(business, owner, variant=variant_a, price=Decimal("999"), quantity=Decimal("1"))
    old.completed_at = timezone.now() - timedelta(days=40)
    old.save(update_fields=("completed_at", "updated_at"))
    cancelled = Sale.objects.create(business=business, currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=cancelled, variant=variant_a, quantity=Decimal("1"), unit_price=Decimal("999"))
    cancel(cancelled, owner)
    product.cost_price = Decimal("1")
    product.save(update_fields=("cost_price", "updated_at"))
    response = api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/products/", {"limit": 10, "period": "last_30_days"})
    assert len(response.data["products"]) == 1
    row = response.data["products"][0]
    assert row["product_public_id"] == product.public_id
    assert row["quantity_sold"] == Decimal("3")
    assert row["revenue"] == Decimal("300")
    assert row["cost_of_goods_sold"] == Decimal("150")
    assert row["gross_margin"] == Decimal("150")
    assert row["margin_rate"] == Decimal("50")
    assert api(employee).get(f"/api/v1/businesses/{business.public_id}/reports/products/").status_code == 404
    assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/products/", {"limit": 51}).status_code == 400


def test_reports_query_cost_and_payload_measurement(capsys):
    small, owner, _, _, category = make_context("measure-small")
    sales_url = f"/api/v1/businesses/{small.public_id}/reports/sales/?period=last_30_days"
    products_url = f"/api/v1/businesses/{small.public_id}/reports/products/?period=last_30_days&limit=10"
    with CaptureQueriesContext(connection) as sales_small: sales_response = api(owner).get(sales_url)
    with CaptureQueriesContext(connection) as products_small: api(owner).get(products_url)
    large, large_owner, _, _, large_category = make_context("measure-large")
    product, _ = add_product(large, large_category, "Measure", Decimal("100"), Decimal("40"))
    for _ in range(8): sell(large, large_owner, product=product)
    large_sales_url = f"/api/v1/businesses/{large.public_id}/reports/sales/?period=last_30_days"
    large_products_url = f"/api/v1/businesses/{large.public_id}/reports/products/?period=last_30_days&limit=10"
    with CaptureQueriesContext(connection) as sales_large: sales_response = api(large_owner).get(large_sales_url)
    with CaptureQueriesContext(connection) as products_large: products_response = api(large_owner).get(large_products_url)
    print(f"REPORT_MEASURE sales={len(sales_small)}/{len(sales_large)} products={len(products_small)}/{len(products_large)} payload={len(sales_response.content)}/{len(products_response.content)}")
    assert len(sales_small) == len(sales_large)
    assert len(products_small) == len(products_large)
