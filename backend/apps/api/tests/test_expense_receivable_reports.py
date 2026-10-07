from decimal import Decimal

import pytest
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.expenses.models import Expense, ExpenseCategory
from apps.receivables.models import Receivable, ReceivablePayment
from apps.sales.models import Customer, Sale


pytestmark = pytest.mark.django_db


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


def test_reports_measurements(capsys):
    business = Business.objects.create(name="Measure reports")
    owner = CarriIdentity.objects.create(carri_subject="measure-reports-owner")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    category = ExpenseCategory.objects.create(business=business, code="MEASURE", name="Measure")
    client = APIClient(); client.force_authenticate(user=owner)
    expenses_url = f"/api/v1/businesses/{business.public_id}/reports/expenses/"
    receivables_url = f"/api/v1/businesses/{business.public_id}/reports/receivables/"
    with CaptureQueriesContext(connection) as expenses_small: client.get(expenses_url)
    with CaptureQueriesContext(connection) as receivables_small: client.get(receivables_url)
    for index in range(12):
        Expense.objects.create(business=business, category=category, amount=Decimal("10"), currency="CDF", payment_method="CASH", expense_date=timezone.localdate(), description="Measure", created_by=owner)
        customer = Customer.objects.create(business=business, name=f"Measure {index}")
        sale = Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=owner)
        receivable = Receivable.objects.create(business=business, sale=sale, customer=customer, currency="CDF", original_amount=Decimal("100"), status="PARTIALLY_PAID")
        ReceivablePayment.objects.create(business=business, receivable=receivable, amount=Decimal("20"), payment_method="CASH", received_by=owner)
    with CaptureQueriesContext(connection) as expenses_large: expenses_response = client.get(expenses_url)
    with CaptureQueriesContext(connection) as receivables_large: receivables_response = client.get(receivables_url)
    print(f"LOT2_MEASURE expenses={len(expenses_small)}/{len(expenses_large)} receivables={len(receivables_small)}/{len(receivables_large)} payload={len(expenses_response.content)}/{len(receivables_response.content)}")
    assert len(expenses_small) == len(expenses_large)
    assert len(receivables_large) - len(receivables_small) <= 1
