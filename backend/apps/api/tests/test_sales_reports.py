from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.finance.models import FinancialMovement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import cancel, complete, create_sale_return


pytestmark = pytest.mark.django_db


def make_context(suffix):
    business = Business.objects.create(name=f"Reports {suffix}")
    owner = CarriIdentity.objects.create(carri_subject=f"reports-owner-{suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"reports-manager-{suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"reports-employee-{suffix}")
    owner_member = BusinessMember.objects.create(
        business=business, identity=owner, role="OWNER"
    )
    manager_member = BusinessMember.objects.create(
        business=business, identity=manager, role="MANAGER"
    )
    BusinessMember.objects.create(
        business=business, identity=employee, role="EMPLOYEE"
    )
    grant_permission(
        owner_member,
        manager_member,
        BusinessMemberPermission.Permission.VIEW_REPORTS,
    )
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


def return_sale(sale, owner, quantity, key, returned_at=None):
    payment_method = FinancialMovement.objects.get(
        sale=sale,
        event_type=FinancialMovement.EventType.SALE_PAYMENT,
    ).payment_transaction.business_payment_method
    return create_sale_return(
        sale=sale,
        actor=owner,
        reason="Reporting return",
        returned_at=returned_at or timezone.now(),
        lines=[
            {
                "sale_line_public_id": sale.lines.get().public_id,
                "quantity": Decimal(quantity),
            }
        ],
        idempotency_key=key,
        refund_payment_method=payment_method,
    )


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
        assert response.data["totals"] == {
            "revenue": Decimal("0"),
            "cost_of_goods_sold": Decimal("0"),
            "sales_revenue": Decimal("0"),
            "returns_revenue": Decimal("0"),
            "net_revenue": Decimal("0"),
            "sales_cogs": Decimal("0"),
            "returns_cogs": Decimal("0"),
            "net_cogs": Decimal("0"),
            "gross_margin": Decimal("0"),
            "sales_count": 0,
            "returns_count": 0,
        }
    assert api(employee).get(url).status_code == 403
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
    assert response.data["totals"]["revenue"] == Decimal("150")
    assert response.data["totals"]["sales_revenue"] == Decimal("150")
    assert response.data["totals"]["returns_revenue"] == Decimal("0")
    assert response.data["totals"]["sales_count"] == 1
    assert response.data["totals"]["returns_count"] == 0
    assert len(response.data["series"]) == 1
    for group_by in ("week", "month"):
        assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/sales/", {"period": "last_30_days", "group_by": group_by}).status_code == 200
    assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/sales/", {"date_from": timezone.localdate().isoformat(), "date_to": timezone.localdate().isoformat()}).data["totals"]["sales_count"] == 1


def test_product_report_groups_variants_uses_snapshots_orders_and_limits():
    business, owner, manager, employee, category = make_context("products")
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
    assert row["sold_quantity"] == Decimal("3")
    assert row["returned_quantity"] == Decimal("0")
    assert row["net_quantity"] == Decimal("3")
    assert row["revenue"] == Decimal("300")
    assert row["sales_revenue"] == Decimal("300")
    assert row["returns_revenue"] == Decimal("0")
    assert row["net_revenue"] == Decimal("300")
    assert row["cost_of_goods_sold"] == Decimal("150")
    assert row["sales_cogs"] == Decimal("150")
    assert row["returns_cogs"] == Decimal("0")
    assert row["net_cogs"] == Decimal("150")
    assert row["gross_margin"] == Decimal("150")
    assert row["margin_rate"] == Decimal("50")
    assert api(manager).get(
        f"/api/v1/businesses/{business.public_id}/reports/products/"
    ).status_code == 200
    assert api(employee).get(f"/api/v1/businesses/{business.public_id}/reports/products/").status_code == 403
    assert api(owner).get(f"/api/v1/businesses/{business.public_id}/reports/products/", {"limit": 51}).status_code == 400


def test_sales_report_partial_total_and_successive_returns_keep_sales_count():
    business, owner, _, _, category = make_context("sales-returns")
    product, _ = add_product(
        business,
        category,
        "Returned product",
        Decimal("100"),
        Decimal("60"),
    )
    sale = sell(business, owner, product=product)
    return_sale(sale, owner, "0.200", "sales-return-one")
    return_sale(sale, owner, "0.300", "sales-return-two")
    url = f"/api/v1/businesses/{business.public_id}/reports/sales/"
    data = api(owner).get(url, {"group_by": "day"}).data
    totals = data["totals"]

    assert totals["sales_revenue"] == Decimal("100")
    assert totals["returns_revenue"] == Decimal("50")
    assert totals["net_revenue"] == totals["revenue"] == Decimal("50")
    assert totals["sales_cogs"] == Decimal("60")
    assert totals["returns_cogs"] == Decimal("30")
    assert totals["net_cogs"] == totals["cost_of_goods_sold"] == Decimal("30")
    assert totals["gross_margin"] == Decimal("20")
    assert totals["sales_count"] == 1
    assert totals["returns_count"] == 2
    assert data["series"][0]["sales_count"] == 1
    assert data["series"][0]["returns_count"] == 2

    total_business, total_owner, _, _, total_category = make_context(
        "sales-total-return"
    )
    total_product, _ = add_product(
        total_business,
        total_category,
        "Total return",
        Decimal("100"),
        Decimal("60"),
    )
    total_sale = sell(total_business, total_owner, product=total_product)
    return_sale(total_sale, total_owner, "1.000", "sales-total-return")
    total = api(total_owner).get(
        f"/api/v1/businesses/{total_business.public_id}/reports/sales/"
    ).data["totals"]
    assert total["net_revenue"] == Decimal("0")
    assert total["net_cogs"] == Decimal("0")
    assert total["gross_margin"] == Decimal("0")
    assert total["sales_count"] == total["returns_count"] == 1


def test_sales_report_places_old_sale_return_in_return_period():
    business, owner, _, _, category = make_context("sales-period")
    product, _ = add_product(
        business,
        category,
        "Period product",
        Decimal("100"),
        Decimal("60"),
    )
    sale = sell(business, owner, product=product)
    sale.completed_at = timezone.make_aware(datetime(2026, 9, 20, 12, 0))
    sale.save(update_fields=("completed_at", "updated_at"))
    return_sale(
        sale,
        owner,
        "0.500",
        "october-report-return",
        returned_at=timezone.make_aware(datetime(2026, 10, 5, 12, 0)),
    )
    url = f"/api/v1/businesses/{business.public_id}/reports/sales/"
    september = api(owner).get(
        url,
        {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "group_by": "month",
        },
    ).data
    october = api(owner).get(
        url,
        {
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
            "group_by": "month",
        },
    ).data

    assert september["totals"]["sales_revenue"] == Decimal("100")
    assert september["totals"]["returns_revenue"] == Decimal("0")
    assert october["totals"]["sales_count"] == 0
    assert october["totals"]["returns_count"] == 1
    assert october["totals"]["net_revenue"] == Decimal("-50")
    assert october["totals"]["net_cogs"] == Decimal("-30")
    assert october["totals"]["gross_margin"] == Decimal("-20")
    assert len(october["series"]) == 1


def test_product_report_merges_product_variant_returns_and_snapshots():
    business, owner, _, _, category = make_context("product-returns")
    product, _ = add_product(
        business,
        category,
        "Parent returns",
        Decimal("100"),
        Decimal("60"),
    )
    product_sale = sell(business, owner, product=product, price=Decimal("100"))
    product.selling_price = Decimal("999")
    product.cost_price = Decimal("888")
    product.save(update_fields=("selling_price", "cost_price", "updated_at"))
    return_sale(product_sale, owner, "0.250", "product-return-one")
    return_sale(product_sale, owner, "0.250", "product-return-two")

    variant = ProductVariant.objects.create(
        product=product,
        attributes={"size": "M"},
        selling_price=Decimal("120"),
        cost_price=Decimal("50"),
    )
    variant_sale = sell(
        business,
        owner,
        variant=variant,
        price=Decimal("120"),
    )
    variant.selling_price = Decimal("777")
    variant.cost_price = Decimal("666")
    variant.save(update_fields=("selling_price", "cost_price", "updated_at"))
    return_sale(variant_sale, owner, "0.500", "variant-return")

    response = api(owner).get(
        f"/api/v1/businesses/{business.public_id}/reports/products/",
        {"limit": 10},
    )
    assert response.status_code == 200
    assert len(response.data["products"]) == 1
    row = response.data["products"][0]
    assert row["product_public_id"] == product.public_id
    assert row["quantity_sold"] == row["sold_quantity"] == Decimal("2")
    assert row["returned_quantity"] == Decimal("1")
    assert row["net_quantity"] == Decimal("1")
    assert row["sales_revenue"] == Decimal("220")
    assert row["returns_revenue"] == Decimal("110")
    assert row["net_revenue"] == row["revenue"] == Decimal("110")
    assert row["sales_cogs"] == Decimal("110")
    assert row["returns_cogs"] == Decimal("55")
    assert row["net_cogs"] == row["cost_of_goods_sold"] == Decimal("55")
    assert row["gross_margin"] == Decimal("55")
    assert row["margin_rate"] == Decimal("50")


def test_product_report_includes_return_only_product_and_preserves_limit():
    business, owner, _, _, category = make_context("return-only")
    product, _ = add_product(
        business,
        category,
        "Return only",
        Decimal("100"),
        Decimal("60"),
    )
    sale = sell(business, owner, product=product)
    sale.completed_at = timezone.make_aware(datetime(2026, 9, 15, 12, 0))
    sale.save(update_fields=("completed_at", "updated_at"))
    return_sale(
        sale,
        owner,
        "0.500",
        "return-only-october",
        returned_at=timezone.make_aware(datetime(2026, 10, 6, 12, 0)),
    )
    other, _ = add_product(
        business,
        category,
        "October sale",
        Decimal("20"),
        Decimal("10"),
    )
    sell(business, owner, product=other, price=Decimal("20"))
    url = f"/api/v1/businesses/{business.public_id}/reports/products/"
    params = {
        "date_from": "2026-10-01",
        "date_to": "2026-10-31",
        "limit": 10,
    }
    products = api(owner).get(url, params).data["products"]
    row = next(value for value in products if value["product_public_id"] == product.public_id)
    assert row["sold_quantity"] == Decimal("0")
    assert row["returned_quantity"] == Decimal("0.500")
    assert row["net_quantity"] == Decimal("-0.500")
    assert row["sales_revenue"] == Decimal("0")
    assert row["returns_revenue"] == Decimal("50")
    assert row["net_revenue"] == Decimal("-50")
    assert len(api(owner).get(url, {**params, "limit": 1}).data["products"]) == 1


def test_reports_isolate_other_business_returns():
    business, owner, _, _, _ = make_context("isolated")
    other, other_owner, _, _, other_category = make_context("isolated-other")
    product, _ = add_product(
        other,
        other_category,
        "Other return",
        Decimal("100"),
        Decimal("60"),
    )
    sale = sell(other, other_owner, product=product)
    return_sale(sale, other_owner, "0.500", "other-business-return")

    base = f"/api/v1/businesses/{business.public_id}/reports/"
    sales = api(owner).get(base + "sales/").data
    products = api(owner).get(base + "products/").data
    assert sales["totals"]["returns_revenue"] == Decimal("0")
    assert sales["totals"]["returns_count"] == 0
    assert products["products"] == []


def test_reports_query_cost_and_payload_measurement():
    small, owner, _, _, category = make_context("measure-small")
    sales_url = f"/api/v1/businesses/{small.public_id}/reports/sales/?period=last_30_days"
    products_url = f"/api/v1/businesses/{small.public_id}/reports/products/?period=last_30_days&limit=10"
    with CaptureQueriesContext(connection) as sales_small: sales_response = api(owner).get(sales_url)
    with CaptureQueriesContext(connection) as products_small: api(owner).get(products_url)
    large, large_owner, _, _, large_category = make_context("measure-large")
    product, _ = add_product(large, large_category, "Measure", Decimal("100"), Decimal("40"))
    sales = [sell(large, large_owner, product=product) for _ in range(8)]
    for index, sale in enumerate(sales[:4]):
        return_sale(sale, large_owner, "0.100", f"measured-return-{index}")
    large_sales_url = f"/api/v1/businesses/{large.public_id}/reports/sales/?period=last_30_days"
    large_products_url = f"/api/v1/businesses/{large.public_id}/reports/products/?period=last_30_days&limit=10"
    with CaptureQueriesContext(connection) as sales_large: sales_response = api(large_owner).get(large_sales_url)
    with CaptureQueriesContext(connection) as products_large: products_response = api(large_owner).get(large_products_url)
    print(f"REPORT_MEASURE sales={len(sales_small)}/{len(sales_large)} products={len(products_small)}/{len(products_large)} payload={len(sales_response.content)}/{len(products_response.content)}")
    assert len(sales_small) == len(sales_large)
    assert len(products_small) == len(products_large)
    assert len(sales_response.content) < 4096
    assert len(products_response.content) < 4096
