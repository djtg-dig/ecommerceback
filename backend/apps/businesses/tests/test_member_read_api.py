from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberPermission,
)
from apps.businesses.services import grant_permission, remove_member


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def create_business_with_owner(suffix):
    business = Business.objects.create(name=f"Members {suffix}")
    identity = CarriIdentity.objects.create(carri_subject=f"owner-{suffix}")
    owner = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=BusinessMember.Role.OWNER,
    )
    return business, identity, owner


def create_member(business, suffix, *, role=BusinessMember.Role.EMPLOYEE):
    identity = CarriIdentity.objects.create(carri_subject=f"member-{suffix}")
    member = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=role,
        title=f"Titre {suffix}",
    )
    return identity, member


def authenticated_client(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def test_member_list_is_compact_paginated_stable_and_excludes_removed_members():
    business, owner_identity, owner = create_business_with_owner("list")
    members = [create_member(business, f"list-{index}")[1] for index in range(55)]
    remove_member(owner, members[0])
    url = f"/api/v1/businesses/{business.public_id}/members/"
    client = authenticated_client(owner_identity)

    first = client.get(url, {"page_size": 5})
    repeated = client.get(url, {"page_size": 5})
    capped = client.get(url, {"page_size": 500})

    assert first.status_code == 200
    assert first.data["count"] == 55
    assert len(first.data["results"]) == 5
    assert len(capped.data["results"]) == 50
    assert first.data["results"] == repeated.data["results"]
    assert first.data["results"][0]["public_id"] == owner.public_id
    assert members[0].public_id not in {
        row["public_id"] for row in capped.data["results"]
    }
    assert set(first.data["results"][0]) == {
        "public_id",
        "title",
        "is_owner",
        "status",
        "permissions",
        "joined_at",
    }
    assert all(row["public_id"].startswith("BM") for row in first.data["results"])


def test_member_detail_is_scoped_and_exposes_prefetched_explicit_permissions():
    business, owner_identity, owner = create_business_with_owner("detail")
    _, target = create_member(business, "detail-target")
    grant_permission(owner, target, Permission.USE_POS)
    grant_permission(owner, target, Permission.VIEW_CATALOG)
    url = (
        f"/api/v1/businesses/{business.public_id}/members/"
        f"{target.public_id}/"
    )

    response = authenticated_client(owner_identity).get(url)

    assert response.status_code == 200
    assert response.data == {
        "public_id": target.public_id,
        "title": target.title,
        "is_owner": False,
        "status": BusinessMember.Status.ACTIVE,
        "permissions": [Permission.USE_POS, Permission.VIEW_CATALOG],
        "joined_at": response.data["joined_at"],
    }

    remove_member(owner, target)
    assert authenticated_client(owner_identity).get(url).status_code == 404


def test_view_members_permission_has_no_legacy_role_or_title_bypass():
    business, owner_identity, owner = create_business_with_owner("permission")
    manager_identity, manager = create_member(
        business,
        "legacy-manager",
        role=BusinessMember.Role.MANAGER,
    )
    url = f"/api/v1/businesses/{business.public_id}/members/"

    assert authenticated_client(owner_identity).get(url).status_code == 200
    assert authenticated_client(manager_identity).get(url).status_code == 403

    grant_permission(owner, manager, Permission.VIEW_MEMBERS)
    assert authenticated_client(manager_identity).get(url).status_code == 200

    manager.status = BusinessMember.Status.SUSPENDED
    manager.save()
    assert authenticated_client(manager_identity).get(url).status_code == 403

    remove_member(owner, manager)
    assert authenticated_client(manager_identity).get(url).status_code == 404


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_authorized_member_reads_remain_available_for_inactive_business(
    business_status,
):
    business, owner_identity, _ = create_business_with_owner(
        f"inactive-{business_status}"
    )
    business.status = business_status
    business.save()

    response = authenticated_client(owner_identity).get(
        f"/api/v1/businesses/{business.public_id}/members/"
    )

    assert response.status_code == 200


def test_member_list_and_detail_never_cross_business_boundaries():
    business_a, owner_a_identity, _ = create_business_with_owner("tenant-a")
    business_b, owner_b_identity, _ = create_business_with_owner("tenant-b")
    _, member_b = create_member(business_b, "tenant-b-target")

    foreign_list = authenticated_client(owner_a_identity).get(
        f"/api/v1/businesses/{business_b.public_id}/members/"
    )
    foreign_detail = authenticated_client(owner_b_identity).get(
        f"/api/v1/businesses/{business_a.public_id}/members/"
        f"{member_b.public_id}/"
    )

    assert foreign_list.status_code == 404
    assert foreign_detail.status_code == 404


def test_member_list_query_count_is_constant_as_dataset_grows():
    small_business, small_identity, _ = create_business_with_owner("queries-small")
    large_business, large_identity, _ = create_business_with_owner("queries-large")
    for index in range(2):
        create_member(small_business, f"queries-small-{index}")
    for index in range(40):
        create_member(large_business, f"queries-large-{index}")

    with CaptureQueriesContext(connection) as small_queries:
        small_response = authenticated_client(small_identity).get(
            f"/api/v1/businesses/{small_business.public_id}/members/",
            {"page_size": 50},
        )
    with CaptureQueriesContext(connection) as large_queries:
        large_response = authenticated_client(large_identity).get(
            f"/api/v1/businesses/{large_business.public_id}/members/",
            {"page_size": 50},
        )

    assert small_response.status_code == 200
    assert large_response.status_code == 200
    assert len(small_queries) == len(large_queries)
    assert len(large_queries) <= 5
