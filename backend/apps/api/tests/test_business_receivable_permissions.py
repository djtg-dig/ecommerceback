import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from apps.businesses.services import grant_permission
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
    business = Business.objects.create(name="Administration permissions")
    other_business = Business.objects.create(name="Other administration tenant")
    owner_identity = CarriIdentity.objects.create(carri_subject="admin-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="admin-manager")
    suspended_identity = CarriIdentity.objects.create(carri_subject="admin-suspended")
    outsider_identity = CarriIdentity.objects.create(carri_subject="admin-outsider")
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
    suspended = BusinessMember.objects.create(
        business=business,
        identity=suspended_identity,
        role=BusinessMember.Role.EMPLOYEE,
        title="Comptable",
    )
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )
    payment_method = BusinessPaymentMethod.objects.create(
        business=business,
        name="Test cash",
        category="CASH",
    )
    customer = Customer.objects.create(business=business, name="Credit customer")
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency=business.primary_currency,
        created_by=owner_identity,
    )
    receivable = Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency=business.primary_currency,
        original_amount="100.00",
    )
    base = f"/api/v1/businesses/{business.public_id}/"

    return {
        "business": business,
        "owner": owner,
        "manager": manager,
        "suspended": suspended,
        "owner_identity": owner_identity,
        "manager_identity": manager_identity,
        "suspended_identity": suspended_identity,
        "outsider_identity": outsider_identity,
        "business_url": base,
        "members_url": base + "members/",
        "methods_url": base + "payment-methods/",
        "method_url": base + f"payment-methods/{payment_method.public_id}/",
        "receivables_url": base + "receivables/",
        "receivable_url": base + f"receivables/{receivable.public_id}/",
        "payments_url": base + f"receivables/{receivable.public_id}/payments/",
    }


def read_urls(context):
    return (
        context["members_url"],
        context["receivables_url"],
        context["receivable_url"],
        context["payments_url"],
    )


def assert_write_status(client, context, expected):
    assert client.patch(
        context["business_url"],
        {"name": "Permission update"},
        format="json",
    ).status_code == expected
    assert client.post(
        context["methods_url"],
        {"name": "Permission method", "category": "CASH"},
        format="json",
    ).status_code == (201 if expected == 200 else expected)
    assert client.patch(
        context["method_url"],
        {"name": "Updated method"},
        format="json",
    ).status_code == expected


def test_owner_has_business_administration_and_receivable_access(permission_context):
    context = permission_context
    owner_client = client_for(context["owner_identity"])

    for url in read_urls(context):
        assert owner_client.get(url).status_code == 200
    assert_write_status(owner_client, context, 200)


def test_legacy_manager_needs_explicit_administration_permissions(
    permission_context,
):
    context = permission_context
    manager_client = client_for(context["manager_identity"])

    for url in read_urls(context):
        assert manager_client.get(url).status_code == 403
    assert_write_status(manager_client, context, 403)

    for permission in (
        Permission.UPDATE_BUSINESS,
        Permission.VIEW_MEMBERS,
        Permission.MANAGE_PAYMENT_METHODS,
        Permission.VIEW_RECEIVABLES,
    ):
        grant_permission(context["owner"], context["manager"], permission)

    for url in read_urls(context):
        assert manager_client.get(url).status_code == 200
    assert_write_status(manager_client, context, 200)


def test_suspended_member_is_forbidden_and_foreign_member_is_hidden(
    permission_context,
):
    context = permission_context
    for permission in (
        Permission.UPDATE_BUSINESS,
        Permission.VIEW_MEMBERS,
        Permission.MANAGE_PAYMENT_METHODS,
        Permission.VIEW_RECEIVABLES,
    ):
        grant_permission(context["owner"], context["suspended"], permission)
    context["suspended"].status = BusinessMember.Status.SUSPENDED
    context["suspended"].save(update_fields=("status", "updated_at"))

    suspended_client = client_for(context["suspended_identity"])
    outsider_client = client_for(context["outsider_identity"])
    for url in read_urls(context):
        assert suspended_client.get(url).status_code == 403
        assert outsider_client.get(url).status_code == 404
    assert_write_status(suspended_client, context, 403)
    assert_write_status(outsider_client, context, 404)


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_inactive_business_allows_authorized_reads_but_blocks_writes(
    permission_context,
    business_status,
):
    context = permission_context
    context["business"].status = business_status
    context["business"].save(update_fields=("status", "updated_at"))
    owner_client = client_for(context["owner_identity"])

    for url in read_urls(context):
        assert owner_client.get(url).status_code == 200
    assert_write_status(owner_client, context, 403)
