from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.expenses.models import Expense, ExpenseCategory, ExpensePayment
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement, reverse_movement
from apps.receivables.models import Receivable, ReceivablePayment
from apps.sales.models import Customer, Sale, SaleReturn

pytestmark = pytest.mark.django_db


def authenticated_client(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def make_context():
    business = Business.objects.create(name="Finance business")
    owner = CarriIdentity.objects.create(carri_subject="finance-owner")
    manager = CarriIdentity.objects.create(carri_subject="finance-manager")
    employee = CarriIdentity.objects.create(carri_subject="finance-employee")
    outsider = CarriIdentity.objects.create(carri_subject="finance-outsider")
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
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )
    category = ExpenseCategory.objects.create(business=business, code="FIN", name="Finance")
    expense = Expense.objects.create(
        business=business, category=category, amount=Decimal("25.00"), currency="CDF",
        payment_method="CASH", expense_date=date(2026, 10, 1), description="Office", created_by=owner,
    )
    customer = Customer.objects.create(business=business, name="Customer")
    sale = Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=owner)
    receivable = Receivable.objects.create(
        business=business, sale=sale, customer=customer, currency="CDF", original_amount=Decimal("50.00"),
    )
    receivable_payment = ReceivablePayment.objects.create(
        business=business, receivable=receivable, amount=Decimal("50.00"), payment_method="CARD", received_by=owner,
    )
    return business, owner, manager, employee, outsider, expense, sale, receivable_payment


def create_expense_movement(business, owner, expense, **overrides):
    amount = overrides.pop("amount", Decimal("25.00"))
    payment_method = overrides.pop("payment_method", "CASH")
    expense_payment = ExpensePayment.objects.create(
        expense=expense,
        amount=amount,
        payment_method=payment_method,
        created_by=owner,
    )
    values = {
        "business": business,
        "direction": FinancialMovement.Direction.OUTFLOW,
        "amount": amount,
        "payment_method": payment_method,
        "event_type": FinancialMovement.EventType.EXPENSE_PAYMENT,
        "created_by": owner,
        "expense_payment": expense_payment,
    }
    values.update(overrides)
    return create_financial_movement(**values)


def test_movement_requires_matching_source_and_business_and_uses_business_currency():
    business, owner, _, _, _, expense, sale, receivable_payment = make_context()
    movement = create_expense_movement(business, owner, expense)
    assert movement.public_id.startswith("FM")
    assert movement.currency == "CDF"

    with pytest.raises(ValidationError):
        create_financial_movement(
            business=business, direction="INFLOW", amount=Decimal("10"), payment_method="CASH",
            event_type=FinancialMovement.EventType.SALE_PAYMENT, created_by=owner, expense=expense,
        )
    other = Business.objects.create(name="Other")
    with pytest.raises(ValidationError):
        create_financial_movement(
            business=other, direction="INFLOW", amount=Decimal("10"), payment_method="CASH",
            event_type=FinancialMovement.EventType.SALE_PAYMENT, created_by=owner, sale=sale,
        )
    receivable_movement = create_financial_movement(
        business=business, direction="INFLOW", amount=Decimal("50"), payment_method="CARD",
        event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT, created_by=owner,
        receivable_payment=receivable_payment,
    )
    assert receivable_movement.receivable_payment_id == receivable_payment.id
    sale_movement = create_financial_movement(
        business=business, direction="INFLOW", amount=Decimal("10"), payment_method="CASH",
        event_type=FinancialMovement.EventType.SALE_PAYMENT, created_by=owner, sale=sale,
    )
    assert sale_movement.sale_id == sale.id
    with pytest.raises(ValidationError):
        create_financial_movement(
            business=business, direction="OUTFLOW", amount=Decimal("25"), payment_method="CASH",
            event_type=FinancialMovement.EventType.EXPENSE_PAYMENT, created_by=owner,
            expense_payment=movement.expense_payment,
        )
    with pytest.raises(ValidationError):
        create_financial_movement(
            business=business, direction="INFLOW", amount=Decimal("10"), payment_method="CASH",
            event_type=FinancialMovement.EventType.SALE_PAYMENT, created_by=owner, sale=sale,
        )
    with pytest.raises(Exception):
        create_financial_movement(
            business=business, direction="INFLOW", amount=Decimal("50"), payment_method="CARD",
            event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT, created_by=owner,
            receivable_payment=receivable_payment,
        )


def test_idempotency_is_scoped_to_business():
    business, owner, _, _, _, expense, _, _ = make_context()
    first = create_expense_movement(business, owner, expense, idempotency_key="expense-1")
    second = create_expense_movement(business, owner, expense, idempotency_key="expense-1")
    assert first.pk == second.pk
    assert FinancialMovement.objects.count() == 1


def test_movement_is_immutable_and_cannot_be_deleted():
    business, owner, _, _, _, expense, _, _ = make_context()
    movement = create_expense_movement(business, owner, expense)
    movement.reason = "changed"
    with pytest.raises(ValidationError):
        movement.save()
    with pytest.raises(ValidationError):
        movement.delete()


def test_expense_payment_can_be_reversed_once_with_opposite_direction():
    business, owner, _, _, _, expense, _, _ = make_context()
    original = create_expense_movement(business, owner, expense)
    reversal = reverse_movement(original, created_by=owner, reason="Duplicate")
    assert reversal.reversal_of_id == original.id
    assert reversal.direction == FinancialMovement.Direction.INFLOW
    assert reversal.amount == original.amount
    with pytest.raises(ValidationError):
        reverse_movement(original, created_by=owner, reason="Again")
    with pytest.raises(ValidationError):
        reverse_movement(reversal, created_by=owner, reason="Chain")


def test_finance_read_api_is_manager_only_tenant_scoped_and_get_only():
    business, owner, manager, employee, outsider, expense, _, _ = make_context()
    movement = create_expense_movement(business, owner, expense)
    root = f"/api/v1/businesses/{business.public_id}/"
    assert authenticated_client(owner).get(root + "financial-movements/").status_code == 200
    assert authenticated_client(manager).get(root + "financial-movements/").status_code == 200
    assert authenticated_client(employee).get(root + "financial-movements/").status_code == 404
    assert authenticated_client(outsider).get(root + "financial-movements/").status_code == 404
    assert authenticated_client(owner).post(root + "financial-movements/", {}, format="json").status_code == 405
    assert authenticated_client(owner).get(
        root + f"financial-movements/{movement.public_id}/"
    ).status_code == 200


def test_finance_filters_summary_grouping_and_ordering():
    business, owner, _, _, _, expense, sale, receivable_payment = make_context()
    expense_movement = create_expense_movement(
        business, owner, expense, amount=Decimal("5000.00")
    )
    sale_movement = create_financial_movement(
        business=business, direction="INFLOW", amount=Decimal("35000.00"),
        payment_method="CASH", event_type=FinancialMovement.EventType.SALE_PAYMENT,
        created_by=owner, sale=sale,
    )
    receivable_movement = create_financial_movement(
        business=business, direction="INFLOW", amount=Decimal("10000.00"),
        payment_method="MOBILE_MONEY",
        event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT, created_by=owner,
        receivable_payment=receivable_payment,
    )
    root = f"/api/v1/businesses/{business.public_id}/"
    client = authenticated_client(owner)
    response = client.get(
        root + "financial-movements/",
        {"direction": "INFLOW", "payment_method": "MOBILE_MONEY"},
    )
    assert response.status_code == 200
    assert [row["public_id"] for row in response.data] == [receivable_movement.public_id]
    all_movements = client.get(root + "financial-movements/")
    assert [row["public_id"] for row in all_movements.data] == [
        receivable_movement.public_id, sale_movement.public_id, expense_movement.public_id,
    ]
    for invalid in (
        {"direction": "SIDEWAYS"}, {"event_type": "UNKNOWN"},
        {"payment_method": "CRYPTO"}, {"date_from": "invalid"}, {"date_to": "2026-15-01"},
    ):
        assert client.get(root + "financial-movements/", invalid).status_code == 400
    summary = client.get(root + "financial-summary/")
    assert summary.status_code == 200
    assert summary.data["currency"] == "CDF"
    assert summary.data["total_inflow"] == Decimal("45000.00")
    assert summary.data["total_outflow"] == Decimal("5000.00")
    assert summary.data["net_flow"] == Decimal("40000.00")
    groups = {entry["payment_method"]: entry for entry in summary.data["by_payment_method"]}
    assert groups["CASH"] == {
        "payment_method": "CASH", "total_inflow": Decimal("35000.00"),
        "total_outflow": Decimal("5000.00"), "net_flow": Decimal("30000.00"),
    }
    assert groups["MOBILE_MONEY"] == {
        "payment_method": "MOBILE_MONEY", "total_inflow": Decimal("10000.00"),
        "total_outflow": Decimal("0"), "net_flow": Decimal("10000.00"),
    }


def test_model_rejects_zero_amount_and_non_business_currency():
    business, owner, _, _, _, expense, _, _ = make_context()
    with pytest.raises(ValidationError):
        create_expense_movement(business, owner, expense, amount=Decimal("0"))
    with pytest.raises(ValidationError):
        FinancialMovement.objects.create(
            business=business, direction="OUTFLOW", amount=Decimal("1"), currency="USD",
            payment_method="CASH", event_type=FinancialMovement.EventType.EXPENSE_PAYMENT,
            occurred_at="2026-10-01T10:00:00Z", created_by=owner, expense=expense,
        )


def test_reversal_requires_reason_and_movement_keeps_explicit_occurred_at():
    business, owner, _, _, _, expense, _, _ = make_context()
    occurred_at = "2026-10-01T10:00:00Z"
    movement = create_expense_movement(business, owner, expense, occurred_at=occurred_at)
    assert movement.occurred_at.isoformat() == "2026-10-01T10:00:00+00:00"
    with pytest.raises(ValidationError):
        reverse_movement(movement, created_by=owner, reason=" ")


def test_detail_rejects_all_public_mutation_methods():
    business, owner, _, _, _, expense, _, _ = make_context()
    movement = create_expense_movement(business, owner, expense)
    detail = f"/api/v1/businesses/{business.public_id}/financial-movements/{movement.public_id}/"
    client = authenticated_client(owner)
    assert client.patch(detail, {}, format="json").status_code == 405
    assert client.put(detail, {}, format="json").status_code == 405
    assert client.delete(detail).status_code == 405


def test_sale_return_refund_source_integrity_and_uniqueness():
    business, owner, _, _, _, expense, sale, _ = make_context()
    sale.status = Sale.Status.COMPLETED
    sale.save(update_fields=("status",))
    sale_return = SaleReturn.objects.create(
        business=business,
        sale=sale,
        customer=sale.customer,
        returned_at=timezone.now(),
        created_by=owner,
        idempotency_key="finance-return",
        idempotency_fingerprint="a" * 64,
    )
    values = {
        "business": business,
        "direction": FinancialMovement.Direction.OUTFLOW,
        "amount": Decimal("1.00"),
        "currency": business.primary_currency,
        "payment_method": "CASH",
        "event_type": FinancialMovement.EventType.SALE_RETURN_REFUND,
        "occurred_at": timezone.now(),
        "created_by": owner,
    }
    movement = FinancialMovement.objects.create(**values, sale_return=sale_return)
    assert movement.sale_return_id == sale_return.id
    assert movement.direction == FinancialMovement.Direction.OUTFLOW
    with pytest.raises(ValidationError):
        FinancialMovement.objects.create(**values)
    with pytest.raises(ValidationError):
        FinancialMovement.objects.create(**values, sale_return=sale_return, sale=sale)
    with pytest.raises(ValidationError):
        FinancialMovement.objects.create(
            **{**values, "event_type": FinancialMovement.EventType.EXPENSE_PAYMENT},
            sale_return=sale_return,
        )
    with pytest.raises(Exception):
        FinancialMovement.objects.create(**values, sale_return=sale_return)
    assert FinancialMovement.objects.filter(expense=expense).count() == 0
