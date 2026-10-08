import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.expenses.models import ExpenseCategory
from apps.expenses.services import ensure_default_expense_categories


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def test_expense_permissions_are_granular_and_title_grants_nothing():
    business = Business.objects.create(name="Expense permission matrix")
    owner_identity = CarriIdentity.objects.create(carri_subject="matrix-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="matrix-manager")
    owner = BusinessMember.objects.create(
        business=business,
        identity=owner_identity,
        role=BusinessMember.Role.OWNER,
    )
    manager = BusinessMember.objects.create(
        business=business,
        identity=manager_identity,
        role=BusinessMember.Role.MANAGER,
        title="Gestionnaire",
    )
    ensure_default_expense_categories(business)
    category = ExpenseCategory.objects.get(business=business, code="RENT")
    base = f"/api/v1/businesses/{business.public_id}/"
    manager_client = client_for(manager_identity)
    expense_payload = {
        "category": category.public_id,
        "amount": "25.00",
        "payment_method": "CASH",
        "expense_date": "2026-10-08",
        "description": "Permission test",
    }

    assert manager_client.get(base + "expenses/").status_code == 403
    assert manager_client.post(
        base + "expenses/",
        expense_payload,
        format="json",
    ).status_code == 403

    grant_permission(owner, manager, Permission.VIEW_EXPENSES)
    assert manager_client.get(base + "expenses/").status_code == 200
    assert manager_client.post(
        base + "expenses/",
        expense_payload,
        format="json",
    ).status_code == 403

    grant_permission(owner, manager, Permission.CREATE_EXPENSES)
    created = manager_client.post(
        base + "expenses/",
        expense_payload,
        format="json",
    )
    assert created.status_code == 201

    category_url = base + "expense-categories/"
    assert manager_client.post(
        category_url,
        {"code": "DENIED", "name": "Denied"},
        format="json",
    ).status_code == 403
    grant_permission(owner, manager, Permission.MANAGE_EXPENSE_CATEGORIES)
    assert manager_client.post(
        category_url,
        {"code": "ALLOWED", "name": "Allowed"},
        format="json",
    ).status_code == 201

    expense_url = base + f"expenses/{created.data['public_id']}/"
    assert manager_client.patch(
        expense_url,
        {"reference": "denied"},
        format="json",
    ).status_code == 403
    grant_permission(owner, manager, Permission.MANAGE_EXPENSES)
    assert manager_client.patch(
        expense_url,
        {"reference": "allowed"},
        format="json",
    ).status_code == 200

    assert client_for(owner_identity).get(base + "expenses/").status_code == 200
