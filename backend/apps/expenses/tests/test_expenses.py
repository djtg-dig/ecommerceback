from datetime import date
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.businesses.services import create_business
from apps.expenses.models import Expense, ExpenseCategory
from apps.expenses.services import ensure_default_expense_categories

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
    for identity, role in ((owner, "OWNER"), (manager, "MANAGER"), (employee, "EMPLOYEE")):
        BusinessMember.objects.create(business=business, identity=identity, role=role)
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
    assert employee_client.patch(detail_url, {"name": "Changed"}, format="json").status_code == 403
    assert owner_client.patch(detail_url, {"name": "Changed"}, format="json").status_code == 400

    custom = owner_client.post(
        base_url(business) + "expense-categories/",
        {"code": "EQUIPMENT", "name": "Equipment"},
        format="json",
    )
    assert custom.status_code == 201
    custom_url = base_url(business) + f"expense-categories/{custom.data['public_id']}/"
    assert manager_client.patch(custom_url, {"is_active": False}, format="json").status_code == 200
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
    assert client(employee).patch(detail_url, {"amount": "11"}, format="json").status_code == 403
    changed = client(manager).patch(
        detail_url,
        {"amount": "11.50", "reference": "INV-42", "expense_date": "2026-10-02"},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.data["amount"] == "11.50"

    cancelled = client(owner).post(detail_url + "cancel/", {"cancellation_reason": "Duplicate"}, format="json")
    assert cancelled.status_code == 200
    assert cancelled.data["status"] == "CANCELLED"
    expense = Expense.objects.get(public_id=created.data["public_id"])
    assert expense.cancelled_by == owner and expense.cancelled_at and expense.cancellation_reason == "Duplicate"
    assert client(owner).post(detail_url + "cancel/", {"cancellation_reason": "Again"}, format="json").status_code == 400
    assert client(manager).patch(detail_url, {"reference": "changed"}, format="json").status_code == 400


def test_expense_category_and_expense_are_tenant_scoped():
    business, owner, _, _, outsider = setup_business()
    other_business = Business.objects.create(name="Other business")
    other_owner = CarriIdentity.objects.create(carri_subject="other-expense-owner")
    BusinessMember.objects.create(business=other_business, identity=other_owner, role="OWNER")
    ensure_default_expense_categories(other_business)
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    other_category = ExpenseCategory.objects.get(business=other_business, code="RENT")
    created = create_expense(client(owner), business, category)

    assert client(other_owner).get(base_url(other_business) + f"expenses/{created.data['public_id']}/").status_code == 404
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
    create_expense(client(owner), business, rent, amount="10", payment_method="CASH", expense_date="2026-10-01")
    second = create_expense(
        client(owner), business, transport, amount="20", currency="USD", payment_method="CARD", expense_date="2026-10-03"
    )
    detail_url = base_url(business) + f"expenses/{second.data['public_id']}/cancel/"
    assert client(owner).post(detail_url, {"cancellation_reason": "Cancelled"}, format="json").status_code == 200
    url = base_url(business) + "expenses/"
    response = client(owner).get(
        url,
        {
            "status": "CANCELLED",
            "currency": "USD",
            "payment_method": "CARD",
            "category": transport.public_id,
            "date_from": "2026-10-02",
            "date_to": "2026-10-04",
        },
    )
    assert response.status_code == 200 and [row["public_id"] for row in response.data] == [second.data["public_id"]]
    for query in ({"status": "UNKNOWN"}, {"currency": "EUR"}, {"payment_method": "CRYPTO"}, {"date_from": "bad-date"}, {"category": "EC0000000000"}):
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
