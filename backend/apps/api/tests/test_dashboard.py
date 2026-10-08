from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission, BusinessPaymentMethod
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory
from apps.inventory.models import InventoryItem
from apps.sales.models import Customer, Sale, SaleLine
from apps.sales.services import complete, create_sale_return

pytestmark = pytest.mark.django_db


def return_context(suffix, amount_paid):
    category, _ = ProductCategory.objects.get_or_create(
        code="DASHRETURN",
        defaults={"name": "Dashboard returns", "slug": "dashboard-returns"},
    )
    business = Business.objects.create(name=f"Dashboard return {suffix}")
    owner = CarriIdentity.objects.create(carri_subject=f"dash-return-{suffix}")
    BusinessMember.objects.create(
        business=business,
        identity=owner,
        role=BusinessMember.Role.OWNER,
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name=f"Return product {suffix}",
        selling_price=Decimal("100"),
        cost_price=Decimal("60"),
        currency="CDF",
        attributes={},
    )
    inventory = InventoryItem.objects.create(
        business=business,
        product=product,
        quantity=Decimal("10"),
    )
    sale = Sale.objects.create(
        business=business,
        customer=Customer.objects.create(
            business=business,
            name=f"Return customer {suffix}",
        ),
        currency="CDF",
        created_by=owner,
    )
    line = SaleLine.objects.create(
        sale=sale,
        product=product,
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
    )
    complete(
        sale,
        owner,
        Decimal(amount_paid),
        "CASH" if Decimal(amount_paid) > 0 else None,
    )
    url = f"/api/v1/businesses/{business.public_id}/dashboard/"
    return business, owner, sale, line, inventory, url


def post_return(sale, owner, line, quantity, key, returned_at=None):
    payment_method = BusinessPaymentMethod.objects.filter(
        business=sale.business,
        category="CASH",
        is_active=True,
    ).first()
    return create_sale_return(
        sale=sale,
        actor=owner,
        reason="Dashboard return",
        returned_at=returned_at or timezone.now(),
        lines=[
            {
                "sale_line_public_id": line.public_id,
                "quantity": Decimal(quantity),
            }
        ],
        idempotency_key=key,
        refund_payment_method=payment_method,
    )


def dashboard_data(user, url, params=None):
    value = APIClient()
    value.force_authenticate(user=user)
    return value.get(url, params or {}).data

def test_dashboard_permissions_and_period_validation():
    business=Business.objects.create(name='Dashboard')
    owner=CarriIdentity.objects.create(carri_subject='dash-owner')
    manager=CarriIdentity.objects.create(carri_subject='dash-manager')
    employee=CarriIdentity.objects.create(carri_subject='dash-employee')
    outsider=CarriIdentity.objects.create(carri_subject='dash-outsider')
    memberships = {
        role: BusinessMember.objects.create(
            business=business,
            identity=identity,
            role=role,
        )
        for identity, role in (
            (owner, "OWNER"),
            (manager, "MANAGER"),
            (employee, "EMPLOYEE"),
        )
    }
    grant_permission(
        memberships["OWNER"],
        memberships["MANAGER"],
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )
    url=f'/api/v1/businesses/{business.public_id}/dashboard/'
    def api(user):
        c=APIClient();c.force_authenticate(user=user);return c
    for user in (owner,manager):
        response=api(user).get(url);assert response.status_code==200;assert set(response.data)=={'generated_at','currency','period','sales','cash','receivables','inventory','purchases'}
    assert api(employee).get(url).status_code==404
    assert api(outsider).get(url).status_code==404
    assert api(owner).get(url,{'period':'last_7_days'}).status_code==200
    assert api(owner).get(url,{'period':'last_30_days'}).status_code==200
    assert api(owner).get(url,{'date_from':'2026-01-01','date_to':'2026-01-02'}).status_code==200
    assert api(owner).get(url,{'date_from':'2026-01-01'}).status_code==400
    assert api(owner).get(url,{'period':'no'}).status_code==400

def test_dashboard_empty_business_has_zero_compact_aggregates():
    business = Business.objects.create(name='Empty dashboard')
    owner = CarriIdentity.objects.create(carri_subject='dash-empty-owner')
    BusinessMember.objects.create(business=business, identity=owner, role='OWNER')
    client = APIClient(); client.force_authenticate(user=owner)
    response = client.get(f'/api/v1/businesses/{business.public_id}/dashboard/')
    assert response.status_code == 200
    assert response.data['currency'] == 'CDF'
    assert response.data['sales'] == {
        'total': Decimal('0'),
        'count': 0,
        'sales_revenue': Decimal('0'),
        'returns_revenue': Decimal('0'),
        'net_revenue': Decimal('0'),
    }
    assert response.data['cash'] == {'inflow': Decimal('0'), 'outflow': Decimal('0'), 'net': Decimal('0')}
    assert response.data['inventory'] == {'out_of_stock_count': 0}

def test_dashboard_sales_completed_lines_are_aggregated_without_line_count_duplication():
    from apps.catalog.models import Product, ProductCategory
    from apps.sales.models import Customer, Sale, SaleLine
    business=Business.objects.create(name='Sales dashboard')
    owner=CarriIdentity.objects.create(carri_subject='dash-sales-owner')
    BusinessMember.objects.create(business=business,identity=owner,role='OWNER')
    category=ProductCategory.objects.create(code='DASHSALE',name='Dashboard',slug='dashboard-sales')
    product=Product.objects.create(business=business,category=category,name='Product',selling_price=Decimal('30000'),currency='CDF',attributes={})
    customer=Customer.objects.create(business=business,name='Customer')
    sale=Sale.objects.create(business=business,customer=customer,currency='CDF',created_by=owner,status='COMPLETED',completed_at=timezone.now())
    SaleLine.objects.create(sale=sale,product=product,quantity=Decimal('1'),unit_price=Decimal('30000'))
    SaleLine.objects.create(sale=sale,product=Product.objects.create(business=business,category=category,name='Product 2',selling_price=Decimal('10000'),currency='CDF',attributes={}),quantity=Decimal('1'),unit_price=Decimal('10000'))
    client=APIClient();client.force_authenticate(user=owner)
    data=client.get(f'/api/v1/businesses/{business.public_id}/dashboard/').data
    assert data['sales'] == {
        'total': Decimal('40000'),
        'count': 1,
        'sales_revenue': Decimal('40000'),
        'returns_revenue': Decimal('0'),
        'net_revenue': Decimal('40000'),
    }


def test_dashboard_cash_uses_financial_movements_and_reversals():
    from datetime import timedelta
    from apps.expenses.models import Expense, ExpenseCategory, ExpensePayment
    from apps.finance.models import FinancialMovement
    from apps.finance.services import create_financial_movement, reverse_movement
    from apps.sales.models import Customer, Sale

    business = Business.objects.create(name='Cash dashboard')
    owner = CarriIdentity.objects.create(carri_subject='dash-cash-owner')
    BusinessMember.objects.create(business=business, identity=owner, role='OWNER')
    customer = Customer.objects.create(business=business, name='Cash customer')
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency='CDF',
        created_by=owner,
    )
    category = ExpenseCategory.objects.create(
        business=business,
        code='DASHCASH',
        name='Dashboard cash',
    )
    expense = Expense.objects.create(
        business=business,
        category=category,
        amount=Decimal('20000'),
        currency='CDF',
        payment_method='CASH',
        expense_date=timezone.localdate(),
        description='Cash expense',
        created_by=owner,
    )
    payment = ExpensePayment.objects.create(
        expense=expense,
        amount=Decimal('20000'),
        payment_method='CASH',
        created_by=owner,
    )
    today = timezone.now()
    create_financial_movement(
        business=business,
        direction=FinancialMovement.Direction.INFLOW,
        amount=Decimal('50000'),
        payment_method='CASH',
        event_type=FinancialMovement.EventType.SALE_PAYMENT,
        created_by=owner,
        sale=sale,
        occurred_at=today,
    )
    outflow = create_financial_movement(
        business=business,
        direction=FinancialMovement.Direction.OUTFLOW,
        amount=Decimal('20000'),
        payment_method='CASH',
        event_type=FinancialMovement.EventType.EXPENSE_PAYMENT,
        created_by=owner,
        expense_payment=payment,
        occurred_at=today,
    )
    client = APIClient()
    client.force_authenticate(user=owner)
    url = f'/api/v1/businesses/{business.public_id}/dashboard/'
    cash = client.get(url).data['cash']
    assert cash == {
        'inflow': Decimal('50000'),
        'outflow': Decimal('20000'),
        'net': Decimal('30000'),
    }
    reverse_movement(outflow, created_by=owner, reason='Correction')
    assert client.get(url).data['cash']['net'] == Decimal('50000')


def test_dashboard_receivables_inventory_and_purchases_are_sql_aggregated():
    from apps.catalog.models import Product, ProductCategory
    from apps.inventory.models import InventoryItem
    from apps.purchases.models import Purchase, PurchaseLine, SupplierPayment
    from apps.receivables.models import Receivable, ReceivablePayment
    from apps.sales.models import Customer, Sale

    business = Business.objects.create(name='Dashboard aggregates')
    owner = CarriIdentity.objects.create(carri_subject='dash-aggregates-owner')
    BusinessMember.objects.create(business=business, identity=owner, role='OWNER')
    customer = Customer.objects.create(business=business, name='Aggregate customer')
    sale = Sale.objects.create(business=business, customer=customer, currency='CDF', created_by=owner)
    receivable = Receivable.objects.create(business=business, sale=sale, customer=customer, currency='CDF', original_amount=Decimal('100000'), status='PARTIALLY_PAID')
    ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal('20000'), payment_method='CASH', received_by=owner)
    ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal('30000'), payment_method='CASH', received_by=owner)
    category = ProductCategory.objects.create(code='DASHAGG', name='Dashboard aggregate', slug='dashboard-aggregate')
    product = Product.objects.create(business=business, category=category, name='Stock zero', selling_price=Decimal('1'), currency='CDF', attributes={})
    product2 = Product.objects.create(business=business, category=category, name='Stock available', selling_price=Decimal('1'), currency='CDF', attributes={})
    InventoryItem.objects.create(business=business, product=product, quantity=Decimal('10'), reserved_quantity=Decimal('10'))
    InventoryItem.objects.create(business=business, product=product2, quantity=Decimal('10'), reserved_quantity=Decimal('3'))
    purchase = Purchase.objects.create(business=business, currency='CDF', created_by=owner, status='CONFIRMED')
    PurchaseLine.objects.create(purchase=purchase, product=product, quantity=Decimal('1'), unit_cost=Decimal('40000'))
    PurchaseLine.objects.create(purchase=purchase, product=product2, quantity=Decimal('1'), unit_cost=Decimal('60000'))
    SupplierPayment.objects.create(purchase=purchase, amount=Decimal('20000'), payment_method='CASH', created_by=owner)
    SupplierPayment.objects.create(purchase=purchase, amount=Decimal('30000'), payment_method='CASH', created_by=owner)
    draft = Purchase.objects.create(business=business, currency='CDF', created_by=owner, status='DRAFT')
    PurchaseLine.objects.create(purchase=draft, product=Product.objects.create(business=business, category=category, name='Draft product', selling_price=Decimal('1'), currency='CDF', attributes={}), quantity=Decimal('1'), unit_cost=Decimal('99999'))
    client = APIClient(); client.force_authenticate(user=owner)
    data = client.get(f'/api/v1/businesses/{business.public_id}/dashboard/').data
    assert data['receivables']['open_count'] == 1
    assert data['receivables']['outstanding_amount'] == Decimal('50000')
    assert data['inventory']['out_of_stock_count'] == 1
    assert data['purchases']['outstanding_amount'] == Decimal('50000')


def test_dashboard_partial_and_total_returns_adjust_revenue_cash_and_stock_once():
    _, owner, sale, line, inventory, url = return_context("paid", "100")
    post_return(sale, owner, line, "0.300", "paid-partial")

    inventory.refresh_from_db()
    partial = dashboard_data(owner, url)
    assert partial["sales"] == {
        "total": Decimal("70"),
        "count": 1,
        "sales_revenue": Decimal("100"),
        "returns_revenue": Decimal("30"),
        "net_revenue": Decimal("70"),
    }
    assert partial["cash"] == {
        "inflow": Decimal("100"),
        "outflow": Decimal("30"),
        "net": Decimal("70"),
    }
    assert inventory.quantity == Decimal("9.300")
    assert partial["inventory"]["out_of_stock_count"] == 0

    post_return(sale, owner, line, "0.700", "paid-total")
    total = dashboard_data(owner, url)
    assert total["sales"]["sales_revenue"] == Decimal("100")
    assert total["sales"]["returns_revenue"] == Decimal("100")
    assert total["sales"]["total"] == total["sales"]["net_revenue"] == Decimal("0")
    assert total["cash"]["outflow"] == Decimal("100")
    assert total["cash"]["net"] == Decimal("0")


def test_dashboard_credit_only_and_mixed_returns_use_real_receivable_balance():
    _, credit_owner, credit_sale, credit_line, _, credit_url = return_context(
        "credit-only",
        "0",
    )
    post_return(
        credit_sale,
        credit_owner,
        credit_line,
        "0.300",
        "credit-only-return",
    )
    credit = dashboard_data(credit_owner, credit_url)
    assert credit["sales"]["total"] == Decimal("70")
    assert credit["cash"] == {
        "inflow": Decimal("0"),
        "outflow": Decimal("0"),
        "net": Decimal("0"),
    }
    assert credit["receivables"] == {
        "open_count": 1,
        "outstanding_amount": Decimal("70"),
        "overdue_count": 0,
    }

    _, mixed_owner, mixed_sale, mixed_line, _, mixed_url = return_context(
        "mixed",
        "40",
    )
    post_return(
        mixed_sale,
        mixed_owner,
        mixed_line,
        "0.700",
        "mixed-return",
    )
    mixed = dashboard_data(mixed_owner, mixed_url)
    assert mixed["sales"]["total"] == Decimal("30")
    assert mixed["cash"] == {
        "inflow": Decimal("40"),
        "outflow": Decimal("10"),
        "net": Decimal("30"),
    }
    assert mixed["receivables"] == {
        "open_count": 0,
        "outstanding_amount": Decimal("0"),
        "overdue_count": 0,
    }


def test_dashboard_returns_follow_returned_at_and_support_successive_returns():
    _, owner, sale, line, _, url = return_context("period", "100")
    sale.completed_at = timezone.make_aware(datetime(2026, 9, 20, 12, 0))
    sale.save(update_fields=("completed_at", "updated_at"))
    october = timezone.make_aware(datetime(2026, 10, 5, 12, 0))
    post_return(sale, owner, line, "0.200", "period-one", returned_at=october)
    post_return(sale, owner, line, "0.300", "period-two", returned_at=october)

    september = dashboard_data(
        owner,
        url,
        {"date_from": "2026-09-01", "date_to": "2026-09-30"},
    )
    october_data = dashboard_data(
        owner,
        url,
        {"date_from": "2026-10-01", "date_to": "2026-10-31"},
    )
    assert september["sales"] == {
        "total": Decimal("100"),
        "count": 1,
        "sales_revenue": Decimal("100"),
        "returns_revenue": Decimal("0"),
        "net_revenue": Decimal("100"),
    }
    assert october_data["sales"] == {
        "total": Decimal("-50"),
        "count": 0,
        "sales_revenue": Decimal("0"),
        "returns_revenue": Decimal("50"),
        "net_revenue": Decimal("-50"),
    }


def test_dashboard_return_aggregates_are_isolated_between_businesses():
    _, owner, _, _, _, url = return_context("isolated-empty", "0")
    _, other_owner, other_sale, other_line, _, _ = return_context(
        "isolated-other",
        "100",
    )
    post_return(
        other_sale,
        other_owner,
        other_line,
        "0.500",
        "other-business-return",
    )

    data = dashboard_data(owner, url)
    assert data["sales"]["returns_revenue"] == Decimal("0")
    assert data["cash"]["outflow"] == Decimal("0")
    assert data["receivables"]["outstanding_amount"] == Decimal("100")


def test_dashboard_query_cost_is_stable_for_enriched_dataset():
    """Measure the existing compact dashboard projection without pinning a magic count."""
    from apps.catalog.models import Product, ProductCategory
    from apps.finance.models import FinancialMovement
    from apps.finance.services import create_financial_movement
    from apps.inventory.models import InventoryItem
    from apps.purchases.models import Purchase, PurchaseLine, SupplierPayment
    from apps.receivables.models import Receivable, ReceivablePayment
    from apps.sales.models import Customer, Sale, SaleLine

    def client_for(business, subject):
        owner = CarriIdentity.objects.create(carri_subject=subject)
        BusinessMember.objects.create(business=business, identity=owner, role='OWNER')
        client = APIClient()
        client.force_authenticate(user=owner)
        return owner, client

    def measure(client, business):
        url = f'/api/v1/businesses/{business.public_id}/dashboard/?period=last_30_days'
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url)
        assert response.status_code == 200
        return len(queries), response, list(queries.captured_queries)

    small_business = Business.objects.create(name='Dashboard measurement small')
    _, small_client = client_for(small_business, 'dashboard-measurement-small')
    small_query_count, _, _ = measure(small_client, small_business)

    business = Business.objects.create(name='Dashboard measurement enriched')
    owner, client = client_for(business, 'dashboard-measurement-enriched')
    category = ProductCategory.objects.create(
        code='DASHMEASURE', name='Dashboard measurement', slug='dashboard-measurement'
    )
    customer = Customer.objects.create(business=business, name='Measurement customer')
    products = [
        Product.objects.create(
            business=business, category=category, name=f'Measurement product {index}',
            selling_price=Decimal('1000'), currency='CDF', attributes={}
        )
        for index in range(12)
    ]
    for index, product in enumerate(products):
        InventoryItem.objects.create(
            business=business, product=product, quantity=Decimal('10'),
            reserved_quantity=Decimal('10') if index % 3 == 0 else Decimal('2'),
        )

    now = timezone.now()
    sales = []
    for index in range(6):
        sale = Sale.objects.create(
            business=business, customer=customer, currency='CDF', created_by=owner,
            status='COMPLETED', completed_at=now,
        )
        for product in products[index * 2:index * 2 + 2]:
            SaleLine.objects.create(
                sale=sale, product=product, quantity=Decimal('1'), unit_price=Decimal('1000')
            )
        sales.append(sale)
        create_financial_movement(
            business=business, direction=FinancialMovement.Direction.INFLOW,
            amount=Decimal('2000'), payment_method='CASH',
            event_type=FinancialMovement.EventType.SALE_PAYMENT, created_by=owner,
            sale=sale, occurred_at=now,
        )

    for sale in sales[:4]:
        receivable = Receivable.objects.create(
            business=business, sale=sale, customer=customer, currency='CDF',
            original_amount=Decimal('2000'), status='PARTIALLY_PAID',
        )
        for amount in (Decimal('400'), Decimal('600')):
            payment = ReceivablePayment.objects.create(
                business=business, receivable=receivable, amount=amount,
                payment_method='CASH', received_by=owner,
            )
            create_financial_movement(
                business=business, direction=FinancialMovement.Direction.INFLOW,
                amount=amount, payment_method='CASH',
                event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT,
                created_by=owner, receivable_payment=payment, occurred_at=now,
            )

    for purchase_index in range(3):
        purchase = Purchase.objects.create(
            business=business, currency='CDF', created_by=owner, status='CONFIRMED'
        )
        for product in products[purchase_index * 4:purchase_index * 4 + 4]:
            PurchaseLine.objects.create(
                purchase=purchase, product=product, quantity=Decimal('1'), unit_cost=Decimal('500')
            )
        for amount in (Decimal('500'), Decimal('700')):
            payment = SupplierPayment.objects.create(
                purchase=purchase, amount=amount, payment_method='CASH', created_by=owner,
            )
            create_financial_movement(
                business=business, direction=FinancialMovement.Direction.OUTFLOW,
                amount=amount, payment_method='CASH',
                event_type=FinancialMovement.EventType.SUPPLIER_PAYMENT,
                created_by=owner, supplier_payment=payment, occurred_at=now,
            )

    for index, sale in enumerate(sales[:3]):
        payment_method = FinancialMovement.objects.get(
            sale=sale,
            event_type=FinancialMovement.EventType.SALE_PAYMENT,
        ).payment_transaction.business_payment_method
        create_sale_return(
            sale=sale,
            actor=owner,
            reason="Measured return",
            returned_at=now,
            lines=[
                {
                    "sale_line_public_id": sale.lines.order_by("public_id").first().public_id,
                    "quantity": Decimal("0.100"),
                }
            ],
            idempotency_key=f"dashboard-measured-return-{index}",
            refund_payment_method=payment_method,
        )

    large_query_count, response, _ = measure(client, business)
    payload_bytes = len(response.content)
    print(
        f'RESULT small_query_count={small_query_count} '
        f'large_query_count={large_query_count} payload_bytes={payload_bytes} '
        f'payload_kilobytes={payload_bytes / 1024:.6f}'
    )
    assert small_query_count == large_query_count
    assert payload_bytes < 2048
