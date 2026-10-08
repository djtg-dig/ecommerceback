from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory, ProductVariant
from apps.expenses.models import Expense, ExpenseCategory
from apps.finance.models import FinancialMovement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.receivables.models import ReceivableAdjustment
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import complete, create_sale_return


pytestmark = pytest.mark.django_db


def context(subject_suffix=""):
    business = Business.objects.create(name="Profitability")
    owner = CarriIdentity.objects.create(carri_subject=f"profit-owner-{subject_suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"profit-manager-{subject_suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"profit-employee-{subject_suffix}")
    owner_member = BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
    )
    manager_member = BusinessMember.objects.create(
        business=business,
        identity=manager,
        role="MANAGER",
    )
    BusinessMember.objects.create(
        business=business,
        identity=employee,
        role="EMPLOYEE",
    )
    grant_permission(
        owner_member,
        manager_member,
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )
    category, _ = ProductCategory.objects.get_or_create(
        code="PROFIT",
        defaults={"name": "Profit", "slug": "profit"},
    )
    product = Product.objects.create(business=business, category=category, name="Product", selling_price=Decimal("100000"), cost_price=Decimal("60000"), currency="CDF", attributes={})
    inventory = InventoryItem.objects.create(business=business, product=product)
    apply_stock_movement(inventory_item=inventory, movement_type=StockMovement.Type.IN, performed_by=owner, quantity=Decimal("20"))
    return business, owner, manager, employee, product


def completed_sale(business, owner, product, amount=Decimal("100000")):
    sale = Sale.objects.create(business=business, customer=Customer.objects.create(business=business, name="Customer"), currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=sale, product=product, quantity=Decimal("1"), unit_price=amount)
    complete(sale, owner, amount, "CASH")
    return sale


def posted_return(sale, owner, quantity, key, returned_at=None):
    payment_method = FinancialMovement.objects.get(
        sale=sale,
        event_type=FinancialMovement.EventType.SALE_PAYMENT,
    ).payment_transaction.business_payment_method
    return create_sale_return(
        sale=sale,
        actor=owner,
        reason="Profitability return",
        returned_at=returned_at or timezone.now(),
        lines=[
            {
                "sale_line_public_id": sale.lines.get().public_id,
                "quantity": quantity,
            }
        ],
        idempotency_key=key,
        refund_payment_method=payment_method,
    )


def client(user):
    value = APIClient()
    value.force_authenticate(user=user)
    return value


def test_profitability_empty_permissions_and_period_validation():
    business, owner, manager, employee, _ = context()
    url = f"/api/v1/businesses/{business.public_id}/profitability-summary/"
    for identity in (owner, manager):
        response = client(identity).get(url)
        assert response.status_code == 200
        assert all(
            response.data[key] == Decimal("0")
            for key in (
                "revenue",
                "cost_of_goods_sold",
                "sales_revenue",
                "returns_revenue",
                "net_revenue",
                "sales_cogs",
                "returns_cogs",
                "net_cogs",
                "gross_margin",
                "expenses",
                "net_result",
            )
        )
    assert client(employee).get(url).status_code == 404
    assert client(owner).get(url, {"period": "bad"}).status_code == 400
    assert client(owner).get(url, {"date_from": "2026-01-02"}).status_code == 400
    assert client(owner).get(url, {"period": "today", "date_from": "2026-01-01", "date_to": "2026-01-02"}).status_code == 400


def test_profitability_uses_completed_sales_snapshots_and_active_expenses_only():
    business, owner, _, _, product = context()
    completed_sale(business, owner, product)
    product.cost_price = Decimal("90000")
    product.save(update_fields=("cost_price", "updated_at"))
    expense_category = ExpenseCategory.objects.create(business=business, code="PROFIT", name="Profit")
    Expense.objects.create(business=business, category=expense_category, amount=Decimal("30000"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Active", created_by=owner)
    Expense.objects.create(business=business, category=expense_category, amount=Decimal("99999"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Cancelled", status="CANCELLED", created_by=owner)
    draft = Sale.objects.create(business=business, currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=draft, product=product, quantity=Decimal("1"), unit_price=Decimal("99999"))
    data = client(owner).get(f"/api/v1/businesses/{business.public_id}/profitability-summary/").data
    assert {key: data[key] for key in ("revenue", "cost_of_goods_sold", "gross_margin", "expenses", "net_result")} == {"revenue": Decimal("100000"), "cost_of_goods_sold": Decimal("60000"), "gross_margin": Decimal("40000"), "expenses": Decimal("30000"), "net_result": Decimal("10000")}
    assert data["sales_revenue"] == data["net_revenue"] == data["revenue"]
    assert data["sales_cogs"] == data["net_cogs"] == data["cost_of_goods_sold"]
    assert data["returns_revenue"] == data["returns_cogs"] == Decimal("0")


def test_profitability_custom_period_excludes_old_sales_and_expenses():
    business, owner, _, _, product = context()
    sale = completed_sale(business, owner, product)
    sale.completed_at = timezone.now() - timedelta(days=40)
    sale.save(update_fields=("completed_at", "updated_at"))
    category = ExpenseCategory.objects.create(business=business, code="OLD", name="Old")
    Expense.objects.create(business=business, category=category, amount=Decimal("50000"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate() - timedelta(days=40), description="Old", created_by=owner)
    response = client(owner).get(f"/api/v1/businesses/{business.public_id}/profitability-summary/", {"period": "last_30_days"})
    assert response.status_code == 200
    assert response.data["net_result"] == Decimal("0")


def test_profitability_partial_return_and_total_return():
    business, owner, _, _, product = context("partial")
    sale = completed_sale(business, owner, product)
    posted_return(sale, owner, Decimal("0.400"), "partial-return")
    data = client(owner).get(
        f"/api/v1/businesses/{business.public_id}/profitability-summary/"
    ).data

    assert data["sales_revenue"] == Decimal("100000")
    assert data["returns_revenue"] == Decimal("40000")
    assert data["net_revenue"] == data["revenue"] == Decimal("60000")
    assert data["sales_cogs"] == Decimal("60000")
    assert data["returns_cogs"] == Decimal("24000")
    assert data["net_cogs"] == data["cost_of_goods_sold"] == Decimal("36000")
    assert data["gross_margin"] == data["net_result"] == Decimal("24000")

    total_business, total_owner, _, _, total_product = context("total")
    total_sale = completed_sale(total_business, total_owner, total_product)
    posted_return(total_sale, total_owner, Decimal("1.000"), "total-return")
    total_data = client(total_owner).get(
        f"/api/v1/businesses/{total_business.public_id}/profitability-summary/"
    ).data
    assert total_data["sales_revenue"] == total_data["returns_revenue"]
    assert total_data["sales_cogs"] == total_data["returns_cogs"]
    assert total_data["net_revenue"] == Decimal("0")
    assert total_data["net_cogs"] == Decimal("0")
    assert total_data["gross_margin"] == total_data["net_result"] == Decimal("0")


def test_profitability_uses_returned_at_independently_from_sale_period():
    business, owner, _, _, product = context("periods")
    sale = completed_sale(business, owner, product)
    sale.completed_at = timezone.make_aware(datetime(2026, 9, 20, 12, 0))
    sale.save(update_fields=("completed_at", "updated_at"))
    posted_return(
        sale,
        owner,
        Decimal("0.500"),
        "october-return",
        returned_at=timezone.make_aware(datetime(2026, 10, 5, 12, 0)),
    )
    url = f"/api/v1/businesses/{business.public_id}/profitability-summary/"

    september = client(owner).get(
        url,
        {"date_from": "2026-09-01", "date_to": "2026-09-30"},
    ).data
    october = client(owner).get(
        url,
        {"date_from": "2026-10-01", "date_to": "2026-10-31"},
    ).data

    assert september["sales_revenue"] == Decimal("100000")
    assert september["returns_revenue"] == Decimal("0")
    assert september["net_revenue"] == Decimal("100000")
    assert october["sales_revenue"] == Decimal("0")
    assert october["returns_revenue"] == Decimal("50000")
    assert october["net_revenue"] == Decimal("-50000")
    assert october["returns_cogs"] == Decimal("30000")
    assert october["net_cogs"] == Decimal("-30000")
    assert october["gross_margin"] == Decimal("-20000")


def test_profitability_multiple_product_and_variant_returns_use_snapshots():
    business, owner, _, _, product = context("targets")
    product_sale = completed_sale(business, owner, product)
    product.selling_price = Decimal("999999")
    product.cost_price = Decimal("888888")
    product.save(update_fields=("selling_price", "cost_price", "updated_at"))
    posted_return(product_sale, owner, Decimal("0.200"), "product-return-one")
    posted_return(product_sale, owner, Decimal("0.300"), "product-return-two")

    variant_product = Product.objects.create(
        business=business,
        category=product.category,
        name="Variant product",
        selling_price=Decimal("80"),
        cost_price=Decimal("30"),
        currency="CDF",
        attributes={},
    )
    variant = ProductVariant.objects.create(
        product=variant_product,
        attributes={"size": "M"},
        selling_price=Decimal("70"),
        cost_price=Decimal("20"),
    )
    variant_inventory = InventoryItem.objects.create(
        business=business,
        variant=variant,
    )
    apply_stock_movement(
        inventory_item=variant_inventory,
        movement_type=StockMovement.Type.IN,
        performed_by=owner,
        quantity=Decimal("5"),
    )
    variant_sale = Sale.objects.create(
        business=business,
        customer=Customer.objects.create(business=business, name="Variant customer"),
        currency="CDF",
        created_by=owner,
    )
    SaleLine.objects.create(
        sale=variant_sale,
        variant=variant,
        quantity=Decimal("1"),
        unit_price=Decimal("70"),
    )
    complete(variant_sale, owner, Decimal("70"), "CASH")
    variant.selling_price = Decimal("777")
    variant.cost_price = Decimal("666")
    variant.save(update_fields=("selling_price", "cost_price", "updated_at"))
    posted_return(variant_sale, owner, Decimal("0.500"), "variant-return")

    data = client(owner).get(
        f"/api/v1/businesses/{business.public_id}/profitability-summary/"
    ).data
    assert data["sales_revenue"] == Decimal("100070")
    assert data["returns_revenue"] == Decimal("50035")
    assert data["sales_cogs"] == Decimal("60020")
    assert data["returns_cogs"] == Decimal("30010")
    assert data["net_revenue"] == Decimal("50035")
    assert data["net_cogs"] == Decimal("30010")


def test_profitability_does_not_double_count_credit_refund_or_expense():
    business, owner, _, _, product = context("economic")
    product.selling_price = Decimal("100")
    product.cost_price = Decimal("60")
    product.save(update_fields=("selling_price", "cost_price", "updated_at"))
    sale = Sale.objects.create(
        business=business,
        customer=Customer.objects.create(business=business, name="Economic customer"),
        currency="CDF",
        created_by=owner,
    )
    SaleLine.objects.create(
        sale=sale,
        product=product,
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
    )
    complete(sale, owner, Decimal("40"), "CASH")
    receivable = sale.receivable
    refund_method = (
        FinancialMovement.objects.get(
            receivable_payment__receivable=receivable,
        ).payment_transaction.business_payment_method
    )
    sale_return = create_sale_return(
        sale=sale,
        actor=owner,
        reason="Economic return",
        returned_at=timezone.now(),
        lines=[
            {
                "sale_line_public_id": sale.lines.get().public_id,
                "quantity": Decimal("0.700"),
            }
        ],
        idempotency_key="economic-return",
        refund_payment_method=refund_method,
    )
    expense_category = ExpenseCategory.objects.create(
        business=business,
        code="ECONOMIC",
        name="Economic",
    )
    Expense.objects.create(
        business=business,
        category=expense_category,
        amount=Decimal("30"),
        currency="CDF",
        payment_method="CASH",
        expense_date=timezone.localdate(),
        description="Unchanged expense",
        created_by=owner,
    )
    assert ReceivableAdjustment.objects.filter(sale_return=sale_return).exists()
    assert FinancialMovement.objects.filter(sale_return=sale_return).exists()

    data = client(owner).get(
        f"/api/v1/businesses/{business.public_id}/profitability-summary/"
    ).data
    assert data["sales_revenue"] == Decimal("100")
    assert data["returns_revenue"] == Decimal("70")
    assert data["net_revenue"] == Decimal("30")
    assert data["sales_cogs"] == Decimal("60")
    assert data["returns_cogs"] == Decimal("42")
    assert data["net_cogs"] == Decimal("18")
    assert data["gross_margin"] == Decimal("12")
    assert data["expenses"] == Decimal("30")
    assert data["net_result"] == Decimal("-18")


def test_profitability_isolates_returns_between_businesses():
    business, owner, _, _, _ = context("isolated-empty")
    other, other_owner, _, _, other_product = context("isolated-other")
    other_sale = completed_sale(other, other_owner, other_product)
    posted_return(other_sale, other_owner, Decimal("0.500"), "other-return")

    data = client(owner).get(
        f"/api/v1/businesses/{business.public_id}/profitability-summary/"
    ).data
    assert data["sales_revenue"] == Decimal("0")
    assert data["returns_revenue"] == Decimal("0")
    assert data["net_result"] == Decimal("0")


def test_profitability_query_cost_is_stable():
    small_business, small_owner, _, _, _ = context("small")
    small_url = f"/api/v1/businesses/{small_business.public_id}/profitability-summary/?period=last_30_days"
    with CaptureQueriesContext(connection) as small_queries:
        assert client(small_owner).get(small_url).status_code == 200

    business, owner, _, _, product = context("large")
    for index in range(3):
        sale = completed_sale(business, owner, product)
        posted_return(
            sale,
            owner,
            Decimal("0.100"),
            f"measured-return-{index}",
        )
    category = ExpenseCategory.objects.create(business=business, code="MEASURE", name="Measure")
    for amount in (Decimal("100"), Decimal("200"), Decimal("300")):
        Expense.objects.create(business=business, category=category, amount=amount, currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Measure", created_by=owner)
    url = f"/api/v1/businesses/{business.public_id}/profitability-summary/?period=last_30_days"
    with CaptureQueriesContext(connection) as large_queries:
        response = client(owner).get(url)
    assert response.status_code == 200
    print(f"PROFITABILITY_MEASURE small={len(small_queries)} large={len(large_queries)} payload={len(response.content)}")
    assert len(small_queries) == len(large_queries)
    assert len(response.content) < 2048
