from datetime import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessPaymentMethod
from apps.catalog.models import Product, ProductCategory
from apps.expenses.models import Expense, ExpenseCategory
from apps.finance.models import FinancialMovement
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.receivables.models import Receivable, ReceivableAdjustment
from apps.sales.models import Customer, Sale, SaleLine, SaleReturnLine
from apps.sales.services import complete, create_sale_return


pytestmark = pytest.mark.django_db


def make_completed_sale(suffix, amount_paid):
    business = Business.objects.create(name=f"Cross-module {suffix}")
    owner = CarriIdentity.objects.create(carri_subject=f"cross-module-{suffix}")
    BusinessMember.objects.create(
        business=business,
        identity=owner,
        role=BusinessMember.Role.OWNER,
    )
    category, _ = ProductCategory.objects.get_or_create(
        code="CROSS",
        defaults={"name": "Cross-module", "slug": "cross-module"},
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Cross-module product",
        selling_price=Decimal("100"),
        cost_price=Decimal("60"),
        currency="CDF",
        attributes={},
    )
    inventory = InventoryItem.objects.create(business=business, product=product)
    apply_stock_movement(
        inventory_item=inventory,
        movement_type=StockMovement.Type.IN,
        performed_by=owner,
        quantity=Decimal("10"),
    )
    customer = Customer.objects.create(business=business, name="Cross customer")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    line = SaleLine.objects.create(
        sale=sale,
        product=product,
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
    )
    complete(sale, owner, Decimal(amount_paid), "CASH")
    sale.refresh_from_db()
    line.refresh_from_db()
    inventory.refresh_from_db()
    return business, owner, product, inventory, sale, line


def api_client(owner):
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


def report_data(client, business, params=None):
    base = f"/api/v1/businesses/{business.public_id}/"
    query = params or {"period": "today"}
    return {
        "profitability": client.get(base + "profitability-summary/", query).data,
        "dashboard": client.get(base + "dashboard/", query).data,
        "sales": client.get(base + "reports/sales/", query).data,
        "products": client.get(base + "reports/products/", query).data,
        "receivables": client.get(base + "reports/receivables/").data,
        "finance": client.get(base + "financial-summary/").data,
    }


def test_sale_return_is_consistent_across_transactional_and_reporting_modules():
    business, owner, product, inventory, sale, line = make_completed_sale(
        "complete-flow",
        Decimal("40"),
    )
    expense_category = ExpenseCategory.objects.create(
        business=business,
        code="CROSS",
        name="Cross-module expense",
    )
    Expense.objects.create(
        business=business,
        category=expense_category,
        amount=Decimal("5"),
        currency="CDF",
        payment_method="CASH",
        expense_date=timezone.localdate(),
        description="Cross-module expense",
        created_by=owner,
    )
    returned_at = timezone.now()
    refund_method = BusinessPaymentMethod.objects.get(
        business=business,
        category="CASH",
        is_active=True,
    )
    return_values = {
        "sale": sale,
        "actor": owner,
        "reason": "Cross-module return",
        "returned_at": returned_at,
        "lines": [
            {
                "sale_line_public_id": line.public_id,
                "quantity": Decimal("0.700"),
            }
        ],
        "idempotency_key": "cross-module-return",
        "refund_payment_method": refund_method,
    }
    sale_return = create_sale_return(**return_values)
    retry = create_sale_return(**return_values)

    assert retry.pk == sale_return.pk
    assert sale_return.receivable_credit_amount == Decimal("60")
    assert sale_return.refund_amount == Decimal("10")
    return_line = SaleReturnLine.objects.get(sale_return=sale_return)
    assert return_line.unit_price_snapshot == Decimal("100")
    assert return_line.unit_cost_snapshot == Decimal("60")
    assert return_line.line_total == Decimal("70")
    assert ReceivableAdjustment.objects.get(sale_return=sale_return).amount == Decimal(
        "60"
    )
    receivable = Receivable.objects.get(sale=sale)
    assert receivable.original_amount == Decimal("100")
    assert receivable.paid_amount == Decimal("40")
    assert receivable.balance == Decimal("0")
    assert receivable.status == Receivable.Status.PAID

    refund = FinancialMovement.objects.get(sale_return=sale_return)
    assert refund.event_type == FinancialMovement.EventType.SALE_RETURN_REFUND
    assert refund.direction == FinancialMovement.Direction.OUTFLOW
    assert refund.amount == Decimal("10")
    inventory.refresh_from_db()
    assert inventory.quantity == Decimal("9.700")
    assert StockMovement.objects.filter(
        inventory_item=inventory,
        movement_type=StockMovement.Type.RETURN,
    ).count() == 1
    sale.refresh_from_db()
    assert sale.status == Sale.Status.COMPLETED

    reports = report_data(api_client(owner), business)
    profitability = reports["profitability"]
    dashboard = reports["dashboard"]
    sales = reports["sales"]["totals"]
    product_row = reports["products"]["products"][0]

    for projection in (profitability, sales):
        assert projection["sales_revenue"] == Decimal("100")
        assert projection["returns_revenue"] == Decimal("70")
        assert projection["net_revenue"] == Decimal("30")
        assert projection["sales_cogs"] == Decimal("60")
        assert projection["returns_cogs"] == Decimal("42")
        assert projection["net_cogs"] == Decimal("18")
        assert projection["gross_margin"] == Decimal("12")
    assert profitability["expenses"] == Decimal("5")
    assert profitability["net_result"] == Decimal("7")
    assert dashboard["sales"]["sales_revenue"] == Decimal("100")
    assert dashboard["sales"]["returns_revenue"] == Decimal("70")
    assert dashboard["sales"]["net_revenue"] == Decimal("30")
    assert dashboard["cash"] == {
        "inflow": Decimal("40"),
        "outflow": Decimal("10"),
        "net": Decimal("30"),
    }
    assert dashboard["receivables"]["outstanding_amount"] == Decimal("0")
    assert reports["receivables"]["total_outstanding"] == Decimal("0")
    assert reports["receivables"]["results"] == []
    assert reports["finance"]["total_inflow"] == Decimal("40")
    assert reports["finance"]["total_outflow"] == Decimal("10")
    assert reports["finance"]["net_flow"] == Decimal("30")
    assert product_row["product_public_id"] == product.public_id
    assert product_row["sold_quantity"] == Decimal("1")
    assert product_row["returned_quantity"] == Decimal("0.700")
    assert product_row["net_quantity"] == Decimal("0.300")
    assert product_row["net_revenue"] == Decimal("30")
    assert product_row["net_cogs"] == Decimal("18")


def test_sale_and_return_periods_match_across_all_economic_projections():
    business, owner, _, _, sale, line = make_completed_sale(
        "separate-periods",
        Decimal("100"),
    )
    sale.completed_at = timezone.make_aware(datetime(2026, 9, 20, 12, 0))
    sale.save(update_fields=("completed_at", "updated_at"))
    refund_method = BusinessPaymentMethod.objects.get(
        business=business,
        category="CASH",
        is_active=True,
    )
    create_sale_return(
        sale=sale,
        actor=owner,
        reason="October correction",
        returned_at=timezone.make_aware(datetime(2026, 10, 5, 12, 0)),
        lines=[
            {
                "sale_line_public_id": line.public_id,
                "quantity": Decimal("0.500"),
            }
        ],
        idempotency_key="cross-module-period-return",
        refund_payment_method=refund_method,
    )
    client = api_client(owner)
    september_params = {"date_from": "2026-09-01", "date_to": "2026-09-30"}
    october_params = {"date_from": "2026-10-01", "date_to": "2026-10-31"}

    september = report_data(client, business, september_params)
    october = report_data(client, business, october_params)

    for projection in (
        september["profitability"],
        september["sales"]["totals"],
    ):
        assert projection["sales_revenue"] == Decimal("100")
        assert projection["returns_revenue"] == Decimal("0")
        assert projection["net_revenue"] == Decimal("100")
        assert projection["net_cogs"] == Decimal("60")
    assert september["dashboard"]["sales"]["net_revenue"] == Decimal("100")
    september_product = september["products"]["products"][0]
    assert september_product["sold_quantity"] == Decimal("1")
    assert september_product["returned_quantity"] == Decimal("0")

    for projection in (
        october["profitability"],
        october["sales"]["totals"],
    ):
        assert projection["sales_revenue"] == Decimal("0")
        assert projection["returns_revenue"] == Decimal("50")
        assert projection["net_revenue"] == Decimal("-50")
        assert projection["returns_cogs"] == Decimal("30")
        assert projection["net_cogs"] == Decimal("-30")
        assert projection["gross_margin"] == Decimal("-20")
    assert october["dashboard"]["sales"]["net_revenue"] == Decimal("-50")
    october_product = october["products"]["products"][0]
    assert october_product["sold_quantity"] == Decimal("0")
    assert october_product["returned_quantity"] == Decimal("0.500")
    assert october_product["net_quantity"] == Decimal("-0.500")
