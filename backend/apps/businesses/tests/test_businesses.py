import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember


def auth(identity):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}"
    )

    return client


@pytest.mark.django_db
def test_create_business_creates_owner_and_is_scoped():
    identity = CarriIdentity.objects.create(carri_subject="owner")

    response = auth(identity).post(
        "/api/v1/businesses/",
        {"name": "Shop", "primary_currency": "CDF"},
        format="json",
    )

    assert response.status_code == 201

    business = Business.objects.get()
    membership = BusinessMember.objects.get(business=business, identity=identity)
    assert membership.role == "OWNER"

    other_identity = CarriIdentity.objects.create(carri_subject="other")
    other_response = auth(other_identity).get(
        f"/api/v1/businesses/{business.public_id}/"
    )
    assert other_response.status_code == 404


@pytest.mark.django_db
def test_roles_control_updates_and_member_list():
    owner = CarriIdentity.objects.create(carri_subject="owner2")
    employee = CarriIdentity.objects.create(carri_subject="employee")
    business = Business.objects.create(name="Shop")

    BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
    )
    BusinessMember.objects.create(
        business=business,
        identity=employee,
        role="EMPLOYEE",
    )

    owner_response = auth(owner).patch(
        f"/api/v1/businesses/{business.public_id}/",
        {"name": "New"},
        format="json",
    )
    assert owner_response.status_code == 200

    employee_update_response = auth(employee).patch(
        f"/api/v1/businesses/{business.public_id}/",
        {"name": "No"},
        format="json",
    )
    assert employee_update_response.status_code == 403

    employee_members_response = auth(employee).get(
        f"/api/v1/businesses/{business.public_id}/members/"
    )
    assert employee_members_response.status_code == 403
