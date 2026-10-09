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
from apps.sales.models import Customer, Sale


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


@pytest.fixture
def permission_context():
    business = Business.objects.create(name="Final permission tenant")
    other_business = Business.objects.create(name="Other final tenant")
    owner_identity = CarriIdentity.objects.create(carri_subject="final-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="final-manager")
    suspended_identity = CarriIdentity.objects.create(carri_subject="final-suspended")
    outsider_identity = CarriIdentity.objects.create(carri_subject="final-outsider")
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
        title="Vendeur",
    )
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )
    active_method = BusinessPaymentMethod.objects.create(
        business=business,
        name="Active cash",
        category="CASH",
    )
    inactive_method = BusinessPaymentMethod.objects.create(
        business=business,
        name="Inactive cash",
        category="CASH",
        is_active=False,
    )
    customer = Customer.objects.create(
        business=business,
        name="Alice Client",
        phone="0990000000",
        email="alice@example.com",
        address="Private address",
        notes="Private notes",
    )
    Customer.objects.create(
        business=business,
        name="Archived customer",
        is_active=False,
    )
    sale = Sale.objects.create(
        business=business,
        customer=customer,
        currency=business.primary_currency,
        created_by=owner_identity,
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
        "active_method": active_method,
        "inactive_method": inactive_method,
        "customer": customer,
        "sale_object": sale,
        "methods": base + "payment-methods/",
        "customers": base + "customers/",
        "pos_customers": base + "customers/pos/search/",
        "sales": base + "sales/",
        "sale": base + f"sales/{sale.public_id}/",
        "lines": base + f"sales/{sale.public_id}/lines/",
    }


def administrative_read_urls(context):
    return (
        context["methods"],
        context["customers"],
        context["sales"],
        context["sale"],
        context["lines"],
    )


def grant_final_permissions(context, member):
    for permission in (
        Permission.VIEW_PAYMENT_METHODS,
        Permission.VIEW_CUSTOMERS,
        Permission.MANAGE_CUSTOMERS,
        Permission.VIEW_SALES,
    ):
        grant_permission(context["owner"], member, permission)


def test_owner_and_explicit_permissions_cover_all_final_operations(permission_context):
    context = permission_context
    owner_client = client_for(context["owner_identity"])

    for url in administrative_read_urls(context):
        assert owner_client.get(url).status_code == 200
    assert owner_client.post(
        context["customers"],
        {"name": "Owner customer"},
        format="json",
    ).status_code == 201

    manager_client = client_for(context["manager_identity"])
    for url in administrative_read_urls(context):
        assert manager_client.get(url).status_code == 403
    assert manager_client.post(
        context["customers"],
        {"name": "Forbidden customer"},
        format="json",
    ).status_code == 403

    grant_final_permissions(context, context["manager"])
    for url in administrative_read_urls(context):
        assert manager_client.get(url).status_code == 200
    assert manager_client.post(
        context["customers"],
        {"name": "Authorized customer"},
        format="json",
    ).status_code == 201


def test_use_pos_gets_only_compact_customers_and_active_payment_methods(
    permission_context,
):
    context = permission_context
    grant_permission(context["owner"], context["manager"], Permission.USE_POS)
    client = client_for(context["manager_identity"])

    methods = client.get(context["methods"])
    assert methods.status_code == 200
    assert {row["public_id"] for row in methods.data} == {
        context["active_method"].public_id,
    }
    assert client.get(
        context["methods"] + f"{context['inactive_method'].public_id}/"
    ).status_code == 404

    customers = client.get(context["pos_customers"], {"q": "Alice"})
    assert customers.status_code == 200
    assert customers.data["count"] == 1
    assert customers.data["results"] == [
        {
            "public_id": context["customer"].public_id,
            "name": "Alice Client",
            "phone": "0990000000",
        }
    ]
    assert client.get(context["customers"]).status_code == 403
    assert client.post(
        context["customers"],
        {"name": "Implicit POS customer"},
        format="json",
    ).status_code == 403
    assert client.get(context["sales"]).status_code == 403
    assert client.post(context["sales"], {}, format="json").status_code == 201


def test_suspended_and_foreign_members_keep_canonical_errors(permission_context):
    context = permission_context
    grant_final_permissions(context, context["suspended"])
    grant_permission(context["owner"], context["suspended"], Permission.USE_POS)
    context["suspended"].status = BusinessMember.Status.SUSPENDED
    context["suspended"].save(update_fields=("status", "updated_at"))

    suspended_client = client_for(context["suspended_identity"])
    outsider_client = client_for(context["outsider_identity"])
    for url in (*administrative_read_urls(context), context["pos_customers"]):
        assert suspended_client.get(url).status_code == 403
        assert outsider_client.get(url).status_code == 404


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_inactive_business_preserves_reads_and_blocks_customer_creation(
    permission_context,
    business_status,
):
    context = permission_context
    context["business"].status = business_status
    context["business"].save(update_fields=("status", "updated_at"))
    owner_client = client_for(context["owner_identity"])

    for url in administrative_read_urls(context):
        assert owner_client.get(url).status_code == 200
    assert owner_client.get(context["pos_customers"]).status_code == 200
    assert owner_client.post(
        context["customers"],
        {"name": "Inactive business customer"},
        format="json",
    ).status_code == 403


def test_new_permissions_do_not_appear_on_existing_non_owner_members(
    permission_context,
):
    context = permission_context

    assert context["manager"].role == BusinessMember.Role.MANAGER
    assert not context["manager"].permissions.filter(
        permission__in=(
            Permission.VIEW_PAYMENT_METHODS,
            Permission.VIEW_CUSTOMERS,
            Permission.MANAGE_CUSTOMERS,
            Permission.VIEW_SALES,
        )
    ).exists()
