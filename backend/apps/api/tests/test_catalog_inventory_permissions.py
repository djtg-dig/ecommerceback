import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberPermission,
)
from apps.businesses.services import grant_permission
from apps.catalog.models import Product, ProductCategory


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


@pytest.fixture
def permission_context():
    category = ProductCategory.objects.create(
        code="PERMISSION_ITEMS",
        name="Permission items",
        slug="permission-items",
    )
    business = Business.objects.create(name="Catalog inventory permissions")
    other_business = Business.objects.create(name="Other catalog tenant")
    owner_identity = CarriIdentity.objects.create(carri_subject="catalog-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="catalog-manager")
    suspended_identity = CarriIdentity.objects.create(carri_subject="catalog-suspended")
    outsider_identity = CarriIdentity.objects.create(carri_subject="catalog-outsider")
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
    )
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Permission product",
        selling_price="10.00",
        currency=business.primary_currency,
        attributes={},
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
        "product": product,
        "products_url": base + "products/",
        "pos_url": base + "products/pos/search/",
        "inventory_url": base + "inventory/",
    }


def test_owner_has_catalog_pos_and_inventory_access(permission_context):
    context = permission_context
    owner_client = client_for(context["owner_identity"])

    assert owner_client.get(context["products_url"]).status_code == 200
    assert owner_client.get(context["pos_url"], {"q": "Permission"}).status_code == 200
    assert owner_client.get(context["inventory_url"]).status_code == 200


def test_legacy_manager_needs_each_explicit_permission(permission_context):
    context = permission_context
    manager_client = client_for(context["manager_identity"])
    product_url = context["products_url"] + f"{context['product'].public_id}/"

    assert manager_client.get(context["products_url"]).status_code == 403
    assert manager_client.patch(
        product_url,
        {"name": "Denied"},
        format="json",
    ).status_code == 403
    assert manager_client.get(context["pos_url"], {"q": "Permission"}).status_code == 403
    assert manager_client.get(context["inventory_url"]).status_code == 403
    assert manager_client.post(
        context["inventory_url"],
        {"product": context["product"].public_id},
        format="json",
    ).status_code == 403

    grants = (
        Permission.VIEW_CATALOG,
        Permission.MANAGE_CATALOG,
        Permission.USE_POS,
        Permission.VIEW_INVENTORY,
        Permission.MANAGE_INVENTORY,
    )
    for permission in grants:
        grant_permission(context["owner"], context["manager"], permission)

    assert manager_client.get(context["products_url"]).status_code == 200
    assert manager_client.patch(
        product_url,
        {"name": "Explicitly allowed"},
        format="json",
    ).status_code == 200
    assert manager_client.get(context["pos_url"], {"q": "allowed"}).status_code == 200
    assert manager_client.get(context["inventory_url"]).status_code == 200
    assert manager_client.post(
        context["inventory_url"],
        {"product": context["product"].public_id},
        format="json",
    ).status_code == 201


def test_suspended_member_is_forbidden_and_foreign_member_is_hidden(
    permission_context,
):
    context = permission_context
    grant_permission(
        context["owner"],
        context["suspended"],
        Permission.VIEW_CATALOG,
    )
    context["suspended"].status = BusinessMember.Status.SUSPENDED
    context["suspended"].save(update_fields=("status", "updated_at"))

    assert client_for(context["suspended_identity"]).get(
        context["products_url"]
    ).status_code == 403
    assert client_for(context["outsider_identity"]).get(
        context["products_url"]
    ).status_code == 404


@pytest.mark.parametrize("business_status", [Business.Status.SUSPENDED, Business.Status.ARCHIVED])
def test_inactive_business_allows_reads_but_blocks_catalog_and_inventory_writes(
    permission_context,
    business_status,
):
    context = permission_context
    context["business"].status = business_status
    context["business"].save(update_fields=("status", "updated_at"))
    owner_client = client_for(context["owner_identity"])
    product_url = context["products_url"] + f"{context['product'].public_id}/"

    assert owner_client.get(context["products_url"]).status_code == 200
    assert owner_client.get(context["pos_url"], {"q": "Permission"}).status_code == 200
    assert owner_client.get(context["inventory_url"]).status_code == 200
    assert owner_client.patch(
        product_url,
        {"name": "Blocked"},
        format="json",
    ).status_code == 403
    assert owner_client.post(
        context["inventory_url"],
        {"product": context["product"].public_id},
        format="json",
    ).status_code == 403
