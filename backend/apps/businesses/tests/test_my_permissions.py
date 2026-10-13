import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import has_permission


def client_for(identity):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}")
    return client


def member(business, subject, *, owner=False, status="ACTIVE"):
    identity = CarriIdentity.objects.create(carri_subject=subject)
    return BusinessMember.objects.create(business=business, identity=identity, role="OWNER" if owner else "EMPLOYEE", is_owner=owner, title="Owner" if owner else "", status=status)


@pytest.mark.django_db
def test_my_permissions_matches_existing_authorization_rules():
    business = Business.objects.create(name="Permissions")
    owner = member(business, "owner", owner=True)
    limited = member(business, "limited")
    empty = member(business, "empty")
    BusinessMemberPermission.objects.create(member=limited, permission="VIEW_CATALOG")
    url = f"/api/v1/businesses/{business.public_id}/my-permissions/"
    all_permissions = list(BusinessMemberPermission.Permission.values)
    for current in (owner, limited, empty):
        response = client_for(current.identity).get(url)
        assert response.status_code == 200
        assert response.data["member_status"] == "ACTIVE"
        assert response.data["permissions"] == [p for p in all_permissions if has_permission(current, p)]


@pytest.mark.django_db
def test_my_permissions_hides_removed_and_external_and_rejects_suspended():
    business = Business.objects.create(name="Permissions status")
    suspended = member(business, "suspended", status="SUSPENDED")
    removed = member(business, "removed", status="REMOVED")
    outsider = CarriIdentity.objects.create(carri_subject="outsider")
    url = f"/api/v1/businesses/{business.public_id}/my-permissions/"
    assert client_for(suspended.identity).get(url).status_code == 403
    assert client_for(removed.identity).get(url).status_code == 404
    assert client_for(outsider).get(url).status_code == 404
    assert client_for(outsider).get("/api/v1/businesses/UNKNOWN/my-permissions/").status_code == 404
    assert APIClient().get(url).status_code == 401
