from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory
from apps.inventory.models import InventoryItem
from apps.receivables.models import Receivable
from apps.sales.models import Customer, Sale


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


@pytest.fixture
def permission_context():
    category = ProductCategory.objects.create(
        code="AUTH_SALES",
        name="Authorized sales",
        slug="authorized-sales",
    )
    business = Business.objects.create(name="Sales permissions")
    owner_identity = CarriIdentity.objects.create(carri_subject="sales-auth-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="sales-auth-manager")
    outsider_identity = CarriIdentity.objects.create(carri_subject="sales-auth-outsider")
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
    other_business = Business.objects.create(name="Other sales tenant")
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Permission product",
        selling_price=Decimal("20.00"),
        cost_price=Decimal("10.00"),
        currency="CDF",
        attributes={},
    )
    InventoryItem.objects.create(
        business=business,
        product=product,
        quantity=Decimal("10.000"),
    )

    return {
        "business": business,
        "owner_identity": owner_identity,
        "manager_identity": manager_identity,
        "outsider_identity": outsider_identity,
        "owner": owner,
        "manager": manager,
        "product": product,
        "base": f"/api/v1/businesses/{business.public_id}/",
    }


def test_pos_mutations_require_permission_and_preserve_owner_access(permission_context):
    context = permission_context
    base = context["base"]
    manager_client = client_for(context["manager_identity"])

    assert manager_client.post(base + "sales/", {}, format="json").status_code == 403
    assert client_for(context["owner_identity"]).post(
        base + "sales/",
        {},
        format="json",
    ).status_code == 201

    grant_permission(context["owner"], context["manager"], Permission.USE_POS)
    created = manager_client.post(base + "sales/", {}, format="json")
    sale_url = base + f"sales/{created.data['public_id']}/"

    assert created.status_code == 201
    assert manager_client.patch(
        sale_url,
        {"reference": "POS-EXPLICIT"},
        format="json",
    ).status_code == 200
    assert manager_client.post(
        sale_url + "lines/",
        {"product": context["product"].public_id, "quantity": "1.000"},
        format="json",
    ).status_code == 201
    assert manager_client.post(
        sale_url + "complete/",
        {"amount_paid": "20.00", "payment_method": "CASH"},
        format="json",
    ).status_code == 200


def test_cancel_requires_manage_sales_not_use_pos(permission_context):
    context = permission_context
    grant_permission(context["owner"], context["manager"], Permission.USE_POS)
    client = client_for(context["manager_identity"])
    created = client.post(context["base"] + "sales/", {}, format="json")
    cancel_url = context["base"] + f"sales/{created.data['public_id']}/cancel/"

    assert client.post(cancel_url, {}, format="json").status_code == 403

    grant_permission(context["owner"], context["manager"], Permission.MANAGE_SALES)
    assert client.post(cancel_url, {}, format="json").status_code == 200


def test_suspended_member_and_foreign_tenant_are_rejected(permission_context):
    context = permission_context
    grant_permission(context["owner"], context["manager"], Permission.USE_POS)
    context["manager"].status = BusinessMember.Status.SUSPENDED
    context["manager"].save()

    assert client_for(context["manager_identity"]).post(
        context["base"] + "sales/",
        {},
        format="json",
    ).status_code == 403
    assert client_for(context["outsider_identity"]).post(
        context["base"] + "sales/",
        {},
        format="json",
    ).status_code == 404


@pytest.mark.parametrize("status", [Business.Status.SUSPENDED, Business.Status.ARCHIVED])
def test_inactive_business_rejects_sale_mutations(permission_context, status):
    context = permission_context
    context["business"].status = status
    context["business"].save()

    assert client_for(context["owner_identity"]).post(
        context["base"] + "sales/",
        {},
        format="json",
    ).status_code == 403


def test_receivable_mutations_require_manage_receivables(permission_context):
    context = permission_context
    customer = Customer.objects.create(
        business=context["business"],
        name="Receivable customer",
    )
    sale = Sale.objects.create(
        business=context["business"],
        customer=customer,
        currency="CDF",
        created_by=context["owner_identity"],
        completed_by=context["owner_identity"],
        status=Sale.Status.COMPLETED,
    )
    receivable = Receivable.objects.create(
        business=context["business"],
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100.00"),
    )
    client = client_for(context["manager_identity"])
    url = context["base"] + f"receivables/{receivable.public_id}/"

    assert client.patch(url, {"notes": "forbidden"}, format="json").status_code == 403
    assert client.post(
        url + "payments/",
        {"amount": "10.00", "payment_method": "CASH"},
        format="json",
    ).status_code == 403

    grant_permission(
        context["owner"],
        context["manager"],
        Permission.MANAGE_RECEIVABLES,
    )
    assert client.patch(url, {"notes": "authorized"}, format="json").status_code == 200
    assert client.post(
        url + "payments/",
        {"amount": "10.00", "payment_method": "CASH"},
        format="json",
    ).status_code == 201
