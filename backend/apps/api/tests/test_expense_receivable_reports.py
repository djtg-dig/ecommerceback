from decimal import Decimal

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.expenses.models import Expense, ExpenseCategory
from apps.receivables.models import Receivable, ReceivableAdjustment, ReceivablePayment
from apps.sales.models import Customer, Sale, SaleReturn


pytestmark = pytest.mark.django_db


def add_return_credit(receivable, actor, amount, suffix):
    sale_return = SaleReturn.objects.create(
        business=receivable.business,
        sale=receivable.sale,
        customer=receivable.customer,
        returned_at=timezone.now(),
        created_by=actor,
        idempotency_key=f"receivables-report-{suffix}",
        idempotency_fingerprint=f"fingerprint-{suffix}",
        receivable_credit_amount=amount,
    )
    return ReceivableAdjustment.objects.create(
        business=receivable.business,
        receivable=receivable,
        sale_return=sale_return,
        adjustment_type=ReceivableAdjustment.Type.RETURN_CREDIT,
        amount=amount,
        created_by=actor,
    )


def test_expense_and_receivable_reports():
    business = Business.objects.create(name="Reports lot 2")
    owner = CarriIdentity.objects.create(carri_subject="reports-lot2-owner")
    employee = CarriIdentity.objects.create(carri_subject="reports-lot2-employee")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    BusinessMember.objects.create(business=business, identity=employee, role="EMPLOYEE")
    category = ExpenseCategory.objects.create(business=business, code="LOT2", name="Lot 2")
    Expense.objects.create(business=business, category=category, amount=Decimal("100"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Active", created_by=owner)
    Expense.objects.create(business=business, category=category, amount=Decimal("999"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Cancelled", status="CANCELLED", created_by=owner)
    customer = Customer.objects.create(business=business, name="Customer")
    sale = Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=owner)
    receivable = Receivable.objects.create(business=business, sale=sale, customer=customer, currency="CDF", original_amount=Decimal("100"), status="PARTIALLY_PAID")
    ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal("20"), payment_method="CASH", received_by=owner)
    ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal("30"), payment_method="CASH", received_by=owner)
    client = APIClient(); client.force_authenticate(user=owner)
    expenses = client.get(f"/api/v1/businesses/{business.public_id}/reports/expenses/")
    assert expenses.status_code == 200 and expenses.data["total_expenses"] == Decimal("100")
    receivables = client.get(f"/api/v1/businesses/{business.public_id}/reports/receivables/")
    assert receivables.status_code == 200
    assert receivables.data["total_outstanding"] == Decimal("50")
    assert receivables.data["results"][0]["outstanding_amount"] == Decimal("50")
    client.force_authenticate(user=employee)
    assert client.get(f"/api/v1/businesses/{business.public_id}/reports/expenses/").status_code == 404
    assert client.get(f"/api/v1/businesses/{business.public_id}/reports/receivables/").status_code == 404


def test_expense_report_categories_periods_and_payments_do_not_change_charge():
    business = Business.objects.create(name="Expenses report")
    owner = CarriIdentity.objects.create(carri_subject="expenses-report-owner")
    manager = CarriIdentity.objects.create(carri_subject="expenses-report-manager")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    BusinessMember.objects.create(business=business, identity=manager, role="MANAGER")
    first = ExpenseCategory.objects.create(business=business, code="FIRST", name="First")
    second = ExpenseCategory.objects.create(business=business, code="SECOND", name="Second")
    for amount, category in ((Decimal("100"), first), (Decimal("300"), second), (Decimal("200"), second)):
        Expense.objects.create(business=business, category=category, amount=amount, currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Expense", created_by=owner)
    old = Expense.objects.create(business=business, category=first, amount=Decimal("999"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate() - __import__("datetime").timedelta(days=40), description="Old", created_by=owner)
    url = f"/api/v1/businesses/{business.public_id}/reports/expenses/"
    response = APIClient(); response.force_authenticate(user=owner)
    data = response.get(url, {"period": "last_30_days", "group_by": "day"}).data
    assert data["total_expenses"] == Decimal("600")
    assert [row["amount"] for row in data["by_category"]] == [Decimal("500"), Decimal("100")]
    for group_by in ("week", "month"):
        assert response.get(url, {"group_by": group_by}).status_code == 200
    assert response.get(url, {"period": "bad"}).status_code == 400
    assert APIClient().get(url).status_code in (401, 403)
    manager_client = APIClient(); manager_client.force_authenticate(user=manager)
    assert manager_client.get(url).status_code == 200


def test_receivables_pagination_overdue_and_customer_aggregation():
    business = Business.objects.create(name="Receivables report")
    owner = CarriIdentity.objects.create(carri_subject="receivables-report-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    customer = Customer.objects.create(business=business, name="Largest")
    for amount, due_date in ((Decimal("100"), timezone.localdate() - __import__("datetime").timedelta(days=1)), (Decimal("70"), None)):
        sale = Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=owner)
        Receivable.objects.create(business=business, sale=sale, customer=customer, currency="CDF", original_amount=amount, status="OPEN", due_date=due_date)
    for index in range(22):
        other = Customer.objects.create(business=business, name=f"Customer {index}")
        sale = Sale.objects.create(business=business, customer=other, currency="CDF", created_by=owner)
        Receivable.objects.create(business=business, sale=sale, customer=other, currency="CDF", original_amount=Decimal("1"), status="OPEN")
    client = APIClient(); client.force_authenticate(user=owner)
    url = f"/api/v1/businesses/{business.public_id}/reports/receivables/"
    data = client.get(url, {"page_size": 1}).data
    assert data["count"] == 23 and len(data["results"]) == 1
    assert data["results"][0]["outstanding_amount"] == Decimal("170")
    assert data["overdue_count"] == 1
    assert client.get(url, {"page_size": 100}).data["results"]


def test_receivables_report_separates_payments_and_return_credits():
    business = Business.objects.create(name="Receivable credits")
    owner = CarriIdentity.objects.create(carri_subject="receivable-credits-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    customer = Customer.objects.create(business=business, name="Adjusted customer")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    receivable = Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("200"),
        status=Receivable.Status.PARTIALLY_PAID,
    )
    payments = [
        ReceivablePayment.objects.create(
            business=business,
            receivable=receivable,
            amount=amount,
            payment_method="CASH",
            received_by=owner,
        )
        for amount in (Decimal("20"), Decimal("30"))
    ]
    adjustments = [
        add_return_credit(receivable, owner, amount, f"separate-{index}")
        for index, amount in enumerate((Decimal("40"), Decimal("10")))
    ]

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get(
        f"/api/v1/businesses/{business.public_id}/reports/receivables/"
    )

    assert response.status_code == 200
    assert response.data["total_outstanding"] == Decimal("100")
    assert response.data["return_credit_amount"] == Decimal("50")
    assert response.data["open_count"] == 1
    assert response.data["results"] == [
        {
            "customer_public_id": customer.public_id,
            "name": customer.name,
            "original_amount": Decimal("200"),
            "paid_amount": Decimal("50"),
            "return_credit_amount": Decimal("50"),
            "outstanding_amount": Decimal("100"),
            "open_receivables_count": 1,
            "overdue_receivables_count": 0,
        }
    ]
    receivable.refresh_from_db()
    assert receivable.original_amount == Decimal("200")
    assert [payment.amount for payment in payments] == [Decimal("20"), Decimal("30")]
    assert [adjustment.amount for adjustment in adjustments] == [
        Decimal("40"),
        Decimal("10"),
    ]


def test_receivables_report_excludes_settled_credit_and_uses_remaining_overdue():
    business = Business.objects.create(name="Settled receivables")
    owner = CarriIdentity.objects.create(carri_subject="settled-receivables-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    customer = Customer.objects.create(business=business, name="Status customer")
    settled_sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    settled = Receivable.objects.create(
        business=business,
        sale=settled_sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100"),
        status=Receivable.Status.PAID,
        due_date=timezone.localdate() - __import__("datetime").timedelta(days=2),
    )
    ReceivablePayment.objects.create(
        business=business,
        receivable=settled,
        amount=Decimal("40"),
        payment_method="CASH",
        received_by=owner,
    )
    add_return_credit(settled, owner, Decimal("60"), "settled")

    open_sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    open_receivable = Receivable.objects.create(
        business=business,
        sale=open_sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100"),
        status=Receivable.Status.OPEN,
        due_date=timezone.localdate() - __import__("datetime").timedelta(days=1),
    )
    add_return_credit(open_receivable, owner, Decimal("30"), "still-open")

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.get(
        f"/api/v1/businesses/{business.public_id}/reports/receivables/"
    )

    assert response.data["total_outstanding"] == Decimal("70")
    assert response.data["open_count"] == 1
    assert response.data["overdue_count"] == 1
    assert response.data["results"][0]["outstanding_amount"] == Decimal("70")
    assert response.data["results"][0]["return_credit_amount"] == Decimal("30")
    assert response.data["results"][0]["overdue_receivables_count"] == 1


def test_receivables_report_permissions_and_business_isolation():
    business = Business.objects.create(name="Visible receivables")
    other_business = Business.objects.create(name="Hidden receivables")
    owner = CarriIdentity.objects.create(carri_subject="visible-receivables-owner")
    manager = CarriIdentity.objects.create(carri_subject="visible-receivables-manager")
    employee = CarriIdentity.objects.create(carri_subject="visible-receivables-employee")
    outsider = CarriIdentity.objects.create(carri_subject="receivables-outsider")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    BusinessMember.objects.create(business=business, identity=manager, role="MANAGER")
    BusinessMember.objects.create(business=business, identity=employee, role="EMPLOYEE")
    other_customer = Customer.objects.create(business=other_business, name="Hidden")
    other_sale = Sale.objects.create(
        business=other_business,
        customer=other_customer,
        currency="CDF",
        created_by=outsider,
    )
    Receivable.objects.create(
        business=other_business,
        sale=other_sale,
        customer=other_customer,
        currency="CDF",
        original_amount=Decimal("999"),
    )
    customer = Customer.objects.create(business=business, name="Visible")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("25"),
    )
    url = f"/api/v1/businesses/{business.public_id}/reports/receivables/"

    for user in (owner, manager):
        client = APIClient()
        client.force_authenticate(user=user)
        response = client.get(url)
        assert response.status_code == 200
        assert response.data["total_outstanding"] == Decimal("25")
        assert response.data["count"] == 1

    for user in (employee, outsider):
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get(url).status_code == 404


def test_reports_measurements(capsys):
    business = Business.objects.create(name="Measure reports")
    owner = CarriIdentity.objects.create(carri_subject="measure-reports-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    category = ExpenseCategory.objects.create(business=business, code="MEASURE", name="Measure")
    client = APIClient(); client.force_authenticate(user=owner)
    expenses_url = f"/api/v1/businesses/{business.public_id}/reports/expenses/"
    receivables_url = f"/api/v1/businesses/{business.public_id}/reports/receivables/"
    Expense.objects.create(
        business=business,
        category=category,
        amount=Decimal("10"),
        currency="CDF",
        payment_method="CASH",
        expense_date=timezone.localdate(),
        description="Small measure",
        created_by=owner,
    )
    customer = Customer.objects.create(business=business, name="Small measure")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency="CDF",
        created_by=owner,
    )
    receivable = Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100"),
        status="PARTIALLY_PAID",
    )
    ReceivablePayment.objects.create(
        business=business,
        receivable=receivable,
        amount=Decimal("20"),
        payment_method="CASH",
        received_by=owner,
    )
    add_return_credit(receivable, owner, Decimal("10"), "measure-small")
    with CaptureQueriesContext(connection) as expenses_small: client.get(expenses_url)
    with CaptureQueriesContext(connection) as receivables_small: client.get(receivables_url)
    for index in range(12):
        Expense.objects.create(business=business, category=category, amount=Decimal("10"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Measure", created_by=owner)
        customer = Customer.objects.create(business=business, name=f"Measure {index}")
        sale = Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=owner)
        receivable = Receivable.objects.create(business=business, sale=sale, customer=customer, currency="CDF", original_amount=Decimal("100"), status="PARTIALLY_PAID")
        ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal("20"), payment_method="CASH", received_by=owner)
        add_return_credit(
            receivable,
            owner,
            Decimal("10"),
            f"measure-{index}",
        )
    with CaptureQueriesContext(connection) as expenses_large: expenses_response = client.get(expenses_url)
    with CaptureQueriesContext(connection) as receivables_large: receivables_response = client.get(receivables_url)
    print(f"LOT2_MEASURE expenses={len(expenses_small)}/{len(expenses_large)} receivables={len(receivables_small)}/{len(receivables_large)} payload={len(expenses_response.content)}/{len(receivables_response.content)}")
    print(
        "B4_MEASURE "
        f"queries={len(receivables_small)}/{len(receivables_large)} "
        f"payload={len(receivables_response.content)}"
    )
    assert len(expenses_small) == len(expenses_large)
    assert len(receivables_large) - len(receivables_small) <= 1
