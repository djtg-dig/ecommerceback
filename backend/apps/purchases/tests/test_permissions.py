import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.services import grant_permission


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


@pytest.fixture
def purchase_permission_context():
    business = Business.objects.create(name="Purchase permissions")
    owner_identity = CarriIdentity.objects.create(carri_subject="purchase-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="purchase-manager")
    outsider_identity = CarriIdentity.objects.create(carri_subject="purchase-outsider")
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
    other_business = Business.objects.create(name="Other purchase tenant")
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )

    return {
        "business": business,
        "owner_identity": owner_identity,
        "manager_identity": manager_identity,
        "outsider_identity": outsider_identity,
        "owner": owner,
        "manager": manager,
        "base": f"/api/v1/businesses/{business.public_id}/",
    }


def test_purchase_read_and_manage_permissions_are_independent(
    purchase_permission_context,
):
    context = purchase_permission_context
    manager_client = client_for(context["manager_identity"])
    suppliers_url = context["base"] + "suppliers/"

    assert manager_client.get(suppliers_url).status_code == 403
    assert manager_client.post(
        suppliers_url,
        {"name": "Forbidden supplier"},
        format="json",
    ).status_code == 403
    assert client_for(context["owner_identity"]).post(
        suppliers_url,
        {"name": "Owner supplier"},
        format="json",
    ).status_code == 201

    grant_permission(context["owner"], context["manager"], Permission.VIEW_PURCHASES)
    assert manager_client.get(suppliers_url).status_code == 200
    assert manager_client.post(
        suppliers_url,
        {"name": "Still forbidden"},
        format="json",
    ).status_code == 403

    grant_permission(
        context["owner"],
        context["manager"],
        Permission.MANAGE_PURCHASES,
    )
    assert manager_client.post(
        suppliers_url,
        {"name": "Explicitly authorized"},
        format="json",
    ).status_code == 201


def test_purchase_permissions_reject_suspended_and_foreign_members(
    purchase_permission_context,
):
    context = purchase_permission_context
    grant_permission(context["owner"], context["manager"], Permission.VIEW_PURCHASES)
    context["manager"].status = BusinessMember.Status.SUSPENDED
    context["manager"].save()
    suppliers_url = context["base"] + "suppliers/"

    assert client_for(context["manager_identity"]).get(suppliers_url).status_code == 403
    assert client_for(context["outsider_identity"]).get(suppliers_url).status_code == 404


@pytest.mark.parametrize("status", [Business.Status.SUSPENDED, Business.Status.ARCHIVED])
def test_inactive_business_allows_purchase_read_but_blocks_write(
    purchase_permission_context,
    status,
):
    context = purchase_permission_context
    context["business"].status = status
    context["business"].save()
    owner_client = client_for(context["owner_identity"])
    suppliers_url = context["base"] + "suppliers/"

    assert owner_client.get(suppliers_url).status_code == 200
    assert owner_client.post(
        suppliers_url,
        {"name": "Blocked supplier"},
        format="json",
    ).status_code == 403
