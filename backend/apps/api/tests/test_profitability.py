from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory
from apps.expenses.models import Expense, ExpenseCategory
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import complete


pytestmark = pytest.mark.django_db


def context(subject_suffix=""):
    business = Business.objects.create(name="Profitability")
    owner = CarriIdentity.objects.create(carri_subject=f"profit-owner-{subject_suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"profit-manager-{subject_suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"profit-employee-{subject_suffix}")
    for identity, role in ((owner, "OWNER"), (manager, "MANAGER"), (employee, "EMPLOYEE")):
        BusinessMember.objects.create(business=business, identity=identity, role=role)
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
        assert all(response.data[key] == Decimal("0") for key in ("revenue", "cost_of_goods_sold", "gross_margin", "expenses", "net_result"))
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


def test_profitability_query_cost_is_stable(capsys):
    small_business, small_owner, _, _, _ = context("small")
    small_url = f"/api/v1/businesses/{small_business.public_id}/profitability-summary/?period=last_30_days"
    with CaptureQueriesContext(connection) as small_queries:
        assert client(small_owner).get(small_url).status_code == 200

    business, owner, _, _, product = context("large")
    for _ in range(3):
        completed_sale(business, owner, product)
    category = ExpenseCategory.objects.create(business=business, code="MEASURE", name="Measure")
    for amount in (Decimal("100"), Decimal("200"), Decimal("300")):
        Expense.objects.create(business=business, category=category, amount=amount, currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Measure", created_by=owner)
    url = f"/api/v1/businesses/{business.public_id}/profitability-summary/?period=last_30_days"
    with CaptureQueriesContext(connection) as large_queries:
        response = client(owner).get(url)
    assert response.status_code == 200
    print(f"PROFITABILITY_MEASURE small={len(small_queries)} large={len(large_queries)} payload={len(response.content)}")
    assert len(small_queries) == len(large_queries)
