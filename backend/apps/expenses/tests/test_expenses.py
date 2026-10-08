from datetime import date
from queue import Queue
from threading import Event, Thread
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import create_business, grant_permission
from apps.common.choices import PaymentMethod
from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.services import (
    add_expense_payment,
    ensure_default_expense_categories,
    update_expense,
)
from apps.receivables.models import ReceivablePayment

pytestmark = pytest.mark.django_db


def client(identity):
    api_client = APIClient()
    api_client.force_authenticate(user=identity)
    return api_client


def setup_business():
    business = Business.objects.create(name="Expenses business")
    owner = CarriIdentity.objects.create(carri_subject="expense-owner")
    manager = CarriIdentity.objects.create(carri_subject="expense-manager")
    employee = CarriIdentity.objects.create(carri_subject="expense-employee")
    outsider = CarriIdentity.objects.create(carri_subject="expense-outsider")
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
    ensure_default_expense_categories(business)
    return business, owner, manager, employee, outsider


def base_url(business):
    return f"/api/v1/businesses/{business.public_id}/"


def create_expense(api_client, business, category, **overrides):
    payload = {
        "category": category.public_id,
        "amount": "10.00",
        "currency": "CDF",
        "payment_method": "CASH",
        "expense_date": "2026-10-01",
        "description": "Loyer",
    }
    payload.update(overrides)
    response = api_client.post(base_url(business) + "expenses/", payload, format="json")
    assert response.status_code == 201, response.data
    return response


def test_category_detail_permissions_system_immutability_and_custom_disable():
    business, owner, manager, employee, _ = setup_business()
    system_category = ExpenseCategory.objects.get(business=business, code="RENT")
    owner_client = client(owner)
    manager_client = client(manager)
    employee_client = client(employee)
    detail_url = base_url(business) + f"expense-categories/{system_category.public_id}/"

    assert employee_client.get(detail_url).status_code == 200
    employee_update = employee_client.patch(
        detail_url,
        {"name": "Changed"},
        format="json",
    )
    assert employee_update.status_code == 403
    system_update = owner_client.patch(
        detail_url,
        {"name": "Changed"},
        format="json",
    )
    assert system_update.status_code == 400

    custom = owner_client.post(
        base_url(business) + "expense-categories/",
        {"code": "EQUIPMENT", "name": "Equipment"},
        format="json",
    )
    assert custom.status_code == 201
    custom_url = base_url(business) + f"expense-categories/{custom.data['public_id']}/"
    custom_update = manager_client.patch(
        custom_url,
        {"is_active": False},
        format="json",
    )
    assert custom_update.status_code == 200
    assert owner_client.post(
        base_url(business) + "expenses/",
        {"category": custom.data["public_id"], "amount": "1", "description": "Invalid"},
        format="json",
    ).status_code == 400


def test_expense_detail_update_and_cancel_workflow():
    business, owner, manager, employee, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    created = create_expense(client(owner), business, category)
    detail_url = base_url(business) + f"expenses/{created.data['public_id']}/"

    assert client(employee).get(detail_url).status_code == 200
    employee_update = client(employee).patch(
        detail_url,
        {"amount": "11"},
        format="json",
    )
    assert employee_update.status_code == 403
    changed = client(manager).patch(
        detail_url,
        {"amount": "11.50", "reference": "INV-42", "expense_date": "2026-10-02"},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["amount"] == "11.50"

    cancelled = client(owner).post(
        detail_url + "cancel/",
        {"cancellation_reason": "Duplicate"},
        format="json",
    )
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "CANCELLED"
    expense = Expense.objects.get(public_id=created.data["public_id"])
    assert expense.cancelled_by == owner
    assert expense.cancelled_at
    assert expense.cancellation_reason == "Duplicate"
    repeated_cancel = client(owner).post(
        detail_url + "cancel/",
        {"cancellation_reason": "Again"},
        format="json",
    )
    assert repeated_cancel.status_code == 400
    cancelled_update = client(manager).patch(
        detail_url,
        {"reference": "changed"},
        format="json",
    )
    assert cancelled_update.status_code == 400


def test_expense_category_and_expense_are_tenant_scoped():
    business, owner, _, _, outsider = setup_business()
    other_business = Business.objects.create(name="Other business")
    other_owner = CarriIdentity.objects.create(carri_subject="other-expense-owner")
    BusinessMember.objects.create(business=other_business, identity=other_owner, role="OWNER")
    ensure_default_expense_categories(other_business)
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    other_category = ExpenseCategory.objects.get(business=other_business, code="RENT")
    created = create_expense(client(owner), business, category)

    cross_tenant_detail = client(other_owner).get(
        base_url(other_business) + f"expenses/{created.data['public_id']}/"
    )
    assert cross_tenant_detail.status_code == 404
    assert client(owner).post(
        base_url(business) + "expenses/",
        {"category": other_category.public_id, "amount": "1", "description": "Cross tenant"},
        format="json",
    ).status_code == 400
    assert client(outsider).get(base_url(business) + "expenses/").status_code == 404


def test_expense_filters_validate_values_and_apply_all_supported_filters():
    business, owner, _, _, _ = setup_business()
    rent = ExpenseCategory.objects.get(business=business, code="RENT")
    transport = ExpenseCategory.objects.get(business=business, code="TRANSPORT")
    create_expense(
        client(owner),
        business,
        rent,
        amount="10",
        payment_method="CASH",
        expense_date="2026-10-01",
    )
    second = create_expense(
        client(owner),
        business,
        transport,
        amount="20",
        currency="CDF",
        payment_method="CARD",
        expense_date="2026-10-03",
    )
    detail_url = base_url(business) + f"expenses/{second.data['public_id']}/cancel/"
    cancellation = client(owner).post(
        detail_url,
        {"cancellation_reason": "Cancelled"},
        format="json",
    )
    assert cancellation.status_code == 200
    url = base_url(business) + "expenses/"
    response = client(owner).get(
        url,
        {
            "status": "CANCELLED",
            "currency": "CDF",
            "payment_method": "CARD",
            "category": transport.public_id,
            "date_from": "2026-10-02",
            "date_to": "2026-10-04",
        },
    )
    assert response.status_code == 200
    assert [row["public_id"] for row in response.data] == [
        second.data["public_id"]
    ]
    invalid_queries = (
        {"status": "UNKNOWN"},
        {"currency": "EUR"},
        {"payment_method": "CRYPTO"},
        {"date_from": "bad-date"},
        {"category": "EC0000000000"},
    )
    for query in invalid_queries:
        assert client(owner).get(url, query).status_code == 400


def test_expense_model_rejects_non_positive_amount_and_category_from_another_business():
    business, owner, _, _, _ = setup_business()
    other_business = Business.objects.create(name="Expense other")
    ensure_default_expense_categories(other_business)
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    other_category = ExpenseCategory.objects.get(business=other_business, code="RENT")
    with pytest.raises(Exception):
        Expense.objects.create(
            business=business,
            category=category,
            amount=0,
            currency="CDF",
            payment_method="CASH",
            expense_date=date.today(),
            description="Invalid",
            created_by=owner,
        )
    with pytest.raises(Exception):
        Expense.objects.create(
            business=business,
            category=other_category,
            amount=1,
            currency="CDF",
            payment_method="CASH",
            expense_date=date.today(),
            description="Invalid tenant",
            created_by=owner,
        )


def test_default_category_service_creates_exact_active_system_categories_idempotently():
    business, _, _, _, _ = setup_business()
    ExpenseCategory.objects.filter(business=business).delete()

    ensure_default_expense_categories(business)
    first_categories = list(ExpenseCategory.objects.filter(business=business).order_by("code"))
    ensure_default_expense_categories(business)
    second_categories = list(ExpenseCategory.objects.filter(business=business).order_by("code"))

    expected_codes = {
        "RENT",
        "ELECTRICITY",
        "WATER",
        "INTERNET",
        "TRANSPORT",
        "SALARY",
        "MAINTENANCE",
        "SUPPLIES",
        "TAX",
        "MARKETING",
        "OTHER",
    }
    assert {category.code for category in first_categories} == expected_codes
    assert len(second_categories) == len(expected_codes)
    assert {category.id for category in first_categories} == {
        category.id for category in second_categories
    }
    assert all(category.business_id == business.id for category in second_categories)
    assert all(category.is_system and category.is_active for category in second_categories)


def test_default_category_service_preserves_existing_category_with_standard_code():
    business = Business.objects.create(name="Existing custom category")
    existing_rent = ExpenseCategory.objects.create(
        business=business,
        code="RENT",
        name="Custom rent label",
        is_system=False,
        is_active=False,
    )

    ensure_default_expense_categories(business)

    categories = ExpenseCategory.objects.filter(business=business)
    rent_categories = categories.filter(code="RENT")
    assert categories.count() == 11
    assert rent_categories.count() == 1
    assert rent_categories.get().id == existing_rent.id
    assert rent_categories.get().name == "Custom rent label"
    assert rent_categories.get().is_system is False


def test_business_api_creation_seeds_default_expense_categories():
    identity = CarriIdentity.objects.create(carri_subject="expense-api-business-owner")
    api_client = client(identity)

    response = api_client.post(
        "/api/v1/businesses/",
        {"name": "Created through API", "primary_currency": "CDF"},
        format="json",
    )

    assert response.status_code == 201, response.data
    business = Business.objects.get(public_id=response.data["public_id"])
    categories = ExpenseCategory.objects.filter(business=business)
    assert categories.count() == 11
    assert set(categories.values_list("code", flat=True)) == {
        "RENT",
        "ELECTRICITY",
        "WATER",
        "INTERNET",
        "TRANSPORT",
        "SALARY",
        "MAINTENANCE",
        "SUPPLIES",
        "TAX",
        "MARKETING",
        "OTHER",
    }


def test_each_business_receives_its_own_standard_category_rows():
    business_a = Business.objects.create(name="Business A")
    business_b = Business.objects.create(name="Business B")

    ensure_default_expense_categories(business_a)
    ensure_default_expense_categories(business_b)

    category_a = ExpenseCategory.objects.get(business=business_a, code="RENT")
    category_b = ExpenseCategory.objects.get(business=business_b, code="RENT")
    assert category_a.id != category_b.id
    assert category_a.code == category_b.code == "RENT"


def test_business_creation_rolls_back_when_expense_initialization_fails():
    identity = CarriIdentity.objects.create(carri_subject="expense-rollback-owner")

    with patch(
        "apps.expenses.services.ensure_default_expense_categories",
        side_effect=RuntimeError("Expense setup unavailable"),
    ):
        with pytest.raises(RuntimeError, match="Expense setup unavailable"):
            create_business(identity, {"name": "Rollback business"})

    assert not Business.objects.filter(name="Rollback business").exists()
    assert not BusinessMember.objects.filter(identity=identity).exists()


def test_payment_method_choices_are_shared_by_expenses_and_receivables():
    expense_choices = Expense._meta.get_field("payment_method").choices
    receivable_payment_choices = ReceivablePayment._meta.get_field(
        "payment_method"
    ).choices

    assert list(expense_choices) == list(PaymentMethod.choices)
    assert list(receivable_payment_choices) == list(PaymentMethod.choices)


@pytest.mark.parametrize("payment_method", PaymentMethod.values)
def test_expense_api_accepts_each_canonical_payment_method(payment_method):
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")

    response = create_expense(
        client(owner),
        business,
        category,
        payment_method=payment_method,
    )

    expense = Expense.objects.get(public_id=response.data["public_id"])
    assert expense.payment_method == payment_method
    assert response.data["payment_method"] == payment_method


def test_expense_api_rejects_non_canonical_payment_method():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")

    response = client(owner).post(
        base_url(business) + "expenses/",
        {
            "category": category.public_id,
            "amount": "10.00",
            "description": "Invalid payment method",
            "payment_method": "BITCOIN",
        },
        format="json",
    )

    assert response.status_code == 400


def test_expense_admin_preserves_financial_history():
    from django.contrib import admin

    from apps.expenses.admin import ExpenseAdmin

    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    created = create_expense(client(owner), business, category)
    expense = Expense.objects.get(public_id=created.data["public_id"])
    expense_admin = ExpenseAdmin(Expense, admin.site)

    assert expense_admin.has_delete_permission(None, expense) is False
    assert "status" in expense_admin.get_readonly_fields(None, expense)

    expense.status = Expense.Status.CANCELLED
    assert set(field.name for field in expense._meta.fields).issubset(
        expense_admin.get_readonly_fields(None, expense)
    )


def test_expense_category_admin_preserves_system_categories():
    from django.contrib import admin

    from apps.expenses.admin import ExpenseCategoryAdmin

    business, _, _, _, _ = setup_business()
    system_category = ExpenseCategory.objects.get(business=business, code="RENT")
    custom_category = ExpenseCategory.objects.create(
        business=business,
        code="CUSTOM_ADMIN",
        name="Custom admin category",
    )
    category_admin = ExpenseCategoryAdmin(ExpenseCategory, admin.site)

    assert category_admin.has_delete_permission(None, system_category) is False
    assert category_admin.has_delete_permission(None, custom_category) is False
    assert {"business", "code", "name", "description", "sort_order"}.issubset(
        category_admin.get_readonly_fields(None, system_category)
    )
    assert "code" not in category_admin.get_readonly_fields(None, custom_category)


def test_expense_rejects_currency_different_from_business_currency():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")

    response = client(owner).post(
        base_url(business) + "expenses/",
        {
            "category": category.public_id,
            "amount": "10.00",
            "currency": "USD",
            "description": "Invalid currency",
        },
        format="json",
    )

    assert response.status_code == 400

from decimal import Decimal
from unittest.mock import patch

from apps.expenses.models import ExpensePayment
from apps.finance.models import FinancialMovement, PaymentTransaction


def expense_payments_url(business, expense):
    return base_url(business) + f"expenses/{expense.public_id}/payments/"


def test_expense_creation_is_not_a_cash_outflow_and_exposes_derived_payment_values():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    response = create_expense(client(owner), business, category, amount="500000.00")
    expense = Expense.objects.get(public_id=response.data["public_id"])
    assert response.data["paid_amount"] == "0"
    assert response.data["balance"] == "500000.00"
    assert response.data["payment_status"] == "UNPAID"
    assert not ExpensePayment.objects.filter(expense=expense).exists()
    assert not FinancialMovement.objects.filter(expense_payment__expense=expense).exists()


def test_expense_payment_lifecycle_idempotency_and_permissions():
    business, owner, manager, employee, outsider = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(public_id=create_expense(client(owner), business, category, amount="100.00").data["public_id"])
    url = expense_payments_url(business, expense)
    assert client(employee).post(url, {"amount": "40", "payment_method": "CASH"}, format="json").status_code == 403
    assert client(outsider).get(url).status_code == 404
    headers = {"HTTP_IDEMPOTENCY_KEY": "expense-payment-retry"}
    first = client(manager).post(url, {"amount": "40", "payment_method": "CASH"}, format="json", **headers)
    retry = client(manager).post(url, {"amount": "40", "payment_method": "CASH"}, format="json", **headers)
    conflict = client(manager).post(url, {"amount": "41", "payment_method": "CASH"}, format="json", **headers)
    assert first.status_code == retry.status_code == 201
    assert first.data["public_id"] == retry.data["public_id"]
    assert conflict.status_code == 409
    payment = ExpensePayment.objects.get(public_id=first.data["public_id"])
    movement = FinancialMovement.objects.get(expense_payment=payment)
    expense.refresh_from_db()
    assert movement.direction == FinancialMovement.Direction.OUTFLOW
    assert movement.amount == payment.amount == Decimal("40.00")
    assert movement.created_by_id == manager.id
    assert movement.payment_transaction_id is not None
    assert movement.payment_transaction.recorded_by_id == manager.id
    assert expense.paid_amount == Decimal("40.00")
    assert expense.balance == Decimal("60.00")
    assert expense.payment_status == Expense.PaymentStatus.PARTIALLY_PAID
    assert client(owner).post(url, {"amount": "61", "payment_method": "CASH"}, format="json").status_code == 400
    with pytest.raises(Exception):
        payment.delete()
    payment.amount = Decimal("1")
    with pytest.raises(Exception):
        payment.save()


def test_expense_payments_reverse_and_cancellation_rules_with_finance_rollback():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    unpaid = Expense.objects.get(public_id=create_expense(client(owner), business, category, amount="100").data["public_id"])
    cancel_url = base_url(business) + f"expenses/{unpaid.public_id}/cancel/"
    assert client(owner).post(cancel_url, {"cancellation_reason": "Duplicate"}, format="json").status_code == 200

    expense = Expense.objects.get(public_id=create_expense(client(owner), business, category, amount="100").data["public_id"])
    url = expense_payments_url(business, expense)
    first = client(owner).post(url, {"amount": "40", "payment_method": "CASH"}, format="json")
    second = client(owner).post(url, {"amount": "30", "payment_method": "MOBILE_MONEY"}, format="json")
    assert first.status_code == second.status_code == 201
    assert client(owner).post(base_url(business) + f"expenses/{expense.public_id}/cancel/", {"cancellation_reason": "No"}, format="json").status_code == 400
    reverse_url = url + f"{second.data['public_id']}/reverse/"
    reversed_response = client(owner).post(reverse_url, {"reason": "Entered twice"}, format="json")
    assert reversed_response.status_code == 200
    assert client(owner).post(reverse_url, {"reason": "Again"}, format="json").status_code == 400
    expense.refresh_from_db()
    assert expense.paid_amount == Decimal("40.00")
    assert expense.balance == Decimal("60.00")
    assert FinancialMovement.objects.filter(expense_payment__expense=expense, direction="OUTFLOW").count() == 2
    assert FinancialMovement.objects.filter(reversal_of__expense_payment__expense=expense, direction="INFLOW").count() == 1
    assert PaymentTransaction.objects.filter(financial_movement__expense_payment__expense=expense).count() == 2

    rollback_expense = Expense.objects.get(public_id=create_expense(client(owner), business, category, amount="10").data["public_id"])
    with patch("apps.expenses.services.create_financial_movement", side_effect=RuntimeError("finance unavailable")):
        with pytest.raises(RuntimeError):
            from apps.expenses.services import add_expense_payment
            add_expense_payment(rollback_expense, owner, Decimal("10"), "CASH")
    assert not ExpensePayment.objects.filter(expense=rollback_expense).exists()


def test_expense_amount_can_be_reduced_without_payments_or_above_paid_total():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(
        public_id=create_expense(
            client(owner),
            business,
            category,
            amount="100.00",
        ).data["public_id"]
    )
    detail_url = base_url(business) + f"expenses/{expense.public_id}/"

    without_payment = client(owner).patch(
        detail_url,
        {"amount": "80.00"},
        format="json",
    )
    assert without_payment.status_code == 200
    assert without_payment.data["amount"] == "80.00"
    assert without_payment.data["balance"] == "80.00"

    payment = client(owner).post(
        expense_payments_url(business, expense),
        {"amount": "30.00", "payment_method": "CASH"},
        format="json",
    )
    assert payment.status_code == 201

    above_paid = client(owner).patch(
        detail_url,
        {"amount": "50.00"},
        format="json",
    )
    assert above_paid.status_code == 200
    assert above_paid.data["paid_amount"] == "30.00"
    assert above_paid.data["balance"] == "20.00"


def test_expense_amount_equal_to_multiple_payments_is_allowed_and_history_is_preserved():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(
        public_id=create_expense(
            client(owner),
            business,
            category,
            amount="100.00",
        ).data["public_id"]
    )
    payments_url = expense_payments_url(business, expense)
    first = client(owner).post(
        payments_url,
        {"amount": "30.00", "payment_method": "CASH"},
        format="json",
    )
    second = client(owner).post(
        payments_url,
        {"amount": "20.00", "payment_method": "MOBILE_MONEY"},
        format="json",
    )
    payment_ids = {first.data["public_id"], second.data["public_id"]}
    movement_ids = set(
        FinancialMovement.objects.filter(
            expense_payment__expense=expense
        ).values_list("public_id", flat=True)
    )

    response = client(owner).patch(
        base_url(business) + f"expenses/{expense.public_id}/",
        {"amount": "50.00"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["amount"] == "50.00"
    assert response.data["paid_amount"] == "50.00"
    assert response.data["balance"] == "0.00"
    assert response.data["payment_status"] == Expense.PaymentStatus.PAID
    assert set(
        ExpensePayment.objects.filter(expense=expense).values_list(
            "public_id", flat=True
        )
    ) == payment_ids
    assert set(
        FinancialMovement.objects.filter(
            expense_payment__expense=expense
        ).values_list("public_id", flat=True)
    ) == movement_ids


def test_expense_amount_below_paid_total_is_rejected_without_any_change():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(
        public_id=create_expense(
            client(owner),
            business,
            category,
            amount="100.00",
            reference="ORIGINAL",
        ).data["public_id"]
    )
    for amount in ("30.00", "20.00"):
        response = client(owner).post(
            expense_payments_url(business, expense),
            {"amount": amount, "payment_method": "CASH"},
            format="json",
        )
        assert response.status_code == 201

    rejected = client(owner).patch(
        base_url(business) + f"expenses/{expense.public_id}/",
        {"amount": "49.99", "reference": "MUST-NOT-PERSIST"},
        format="json",
    )

    assert rejected.status_code == 400
    assert rejected.data == {
        "detail": {
            "amount": ["Amount cannot be lower than the total already paid."]
        }
    }
    expense.refresh_from_db()
    assert expense.amount == Decimal("100.00")
    assert expense.reference == "ORIGINAL"
    assert expense.paid_amount == Decimal("50.00")
    assert expense.balance == Decimal("50.00")

    expense.amount = Decimal("49.99")
    with pytest.raises(
        ValidationError,
        match="Amount cannot be lower than the total already paid",
    ):
        expense.save()
    expense.refresh_from_db()
    assert expense.amount == Decimal("100.00")


def test_expense_amount_update_permissions_isolation_and_put_cannot_bypass_guard():
    business, owner, _, employee, _ = setup_business()
    other_business = Business.objects.create(name="Other expense tenant")
    other_owner = CarriIdentity.objects.create(carri_subject="other-expense-p0")
    BusinessMember.objects.create(
        business=other_business,
        identity=other_owner,
        role=BusinessMember.Role.OWNER,
    )
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(
        public_id=create_expense(
            client(owner),
            business,
            category,
            amount="100.00",
        ).data["public_id"]
    )
    add_expense_payment(expense, owner, Decimal("40.00"), "CASH")
    detail_url = base_url(business) + f"expenses/{expense.public_id}/"

    assert client(employee).patch(
        detail_url,
        {"amount": "30.00"},
        format="json",
    ).status_code == 403
    assert client(other_owner).patch(
        base_url(other_business) + f"expenses/{expense.public_id}/",
        {"amount": "30.00"},
        format="json",
    ).status_code == 404
    assert client(owner).put(
        detail_url,
        {"amount": "30.00"},
        format="json",
    ).status_code == 405

    expense.refresh_from_db()
    assert expense.amount == Decimal("100.00")
    assert expense.balance == Decimal("60.00")


@pytest.mark.django_db(transaction=True)
def test_concurrent_expense_reduction_and_payment_are_serialized():
    business, owner, _, _, _ = setup_business()
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    expense = Expense.objects.get(
        public_id=create_expense(
            client(owner),
            business,
            category,
            amount="100.00",
        ).data["public_id"]
    )
    amount_lock_acquired = Event()
    release_amount_update = Event()
    payment_started = Event()
    outcomes = Queue()

    def reduce_amount():
        close_old_connections()
        try:
            with transaction.atomic():
                locked_expense = Expense.objects.select_for_update().get(
                    pk=expense.pk
                )
                amount_lock_acquired.set()
                if not release_amount_update.wait(timeout=5):
                    raise RuntimeError("Timed out waiting to release amount update.")
                update_expense(
                    locked_expense,
                    {"amount": Decimal("50.00")},
                )
            outcomes.put(("amount", None))
        except Exception as error:
            outcomes.put(("amount", error))
        finally:
            close_old_connections()

    def pay_expense():
        close_old_connections()
        payment_started.set()
        try:
            add_expense_payment(
                expense,
                owner,
                Decimal("60.00"),
                "CASH",
            )
            outcomes.put(("payment", None))
        except Exception as error:
            outcomes.put(("payment", error))
        finally:
            close_old_connections()

    amount_thread = Thread(target=reduce_amount)
    payment_thread = Thread(target=pay_expense)
    amount_thread.start()
    assert amount_lock_acquired.wait(timeout=5)
    payment_thread.start()
    assert payment_started.wait(timeout=5)
    release_amount_update.set()
    amount_thread.join(timeout=10)
    payment_thread.join(timeout=10)

    assert not amount_thread.is_alive()
    assert not payment_thread.is_alive()
    results = dict(outcomes.get(timeout=1) for _ in range(2))
    assert results["amount"] is None
    assert isinstance(results["payment"], ValidationError)
    assert "Payment exceeds the remaining expense balance" in str(
        results["payment"]
    )

    expense.refresh_from_db()
    assert expense.amount == Decimal("50.00")
    assert expense.paid_amount == Decimal("0")
    assert expense.balance == Decimal("50.00")
    assert not ExpensePayment.objects.filter(expense=expense).exists()
