import json

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
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
    business = Business.objects.create(name=f"Lifecycle {suffix}")
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


def member_url(business, member):
    return f"/api/v1/businesses/{business.public_id}/members/{member.public_id}/"


def test_owner_can_update_title_of_member():
    business, owner_identity, owner = create_business_with_owner("title-owner")
    _, member = create_member(business, "title-target")

    response = authenticated_client(owner_identity).patch(
        member_url(business, member),
        {"title": "Caissier principal"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["title"] == "Caissier principal"
    assert response.data["is_owner"] is False
    assert response.data["status"] == BusinessMember.Status.ACTIVE
    member.refresh_from_db()
    assert member.title == "Caissier principal"
    assert member.is_owner is False
    assert member.status == BusinessMember.Status.ACTIVE


def test_owner_can_update_title_of_owner_without_losing_ownership():
    business, owner_identity, owner = create_business_with_owner("title-self")

    response = authenticated_client(owner_identity).patch(
        member_url(business, owner),
        {"title": "Directeur"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["is_owner"] is True
    owner.refresh_from_db()
    assert owner.title == "Directeur"
    assert owner.is_owner is True
    assert owner.status == BusinessMember.Status.ACTIVE


def test_title_update_rejects_payload_escalation():
    business, owner_identity, owner = create_business_with_owner("title-escalation")
    _, member = create_member(business, "title-escalation-target")

    response = authenticated_client(owner_identity).patch(
        member_url(business, member),
        {
            "title": "Caissier",
            "is_owner": True,
            "status": "SUSPENDED",
            "role": "OWNER",
            "identity": str(member.identity_id),
            "business": str(business.id),
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["title"] == "Caissier"
    assert response.data["is_owner"] is False
    assert response.data["status"] == BusinessMember.Status.ACTIVE
    member.refresh_from_db()
    assert member.is_owner is False
    assert member.status == BusinessMember.Status.ACTIVE
    assert member.role == BusinessMember.Role.EMPLOYEE


def test_title_update_requires_non_empty_title():
    business, owner_identity, owner = create_business_with_owner("title-blank")
    _, member = create_member(business, "title-blank-target")

    response = authenticated_client(owner_identity).patch(
        member_url(business, member),
        {"title": ""},
        format="json",
    )

    assert response.status_code == 400
    member.refresh_from_db()
    assert member.title == "Titre title-blank-target"


def test_manage_members_permission_allows_title_update():
    business, owner_identity, owner = create_business_with_owner("title-manager")
    manager_identity, manager = create_member(business, "title-manager-actor")
    _, member = create_member(business, "title-manager-target")

    assert authenticated_client(manager_identity).patch(
        member_url(business, member),
        {"title": "Nouveau titre"},
        format="json",
    ).status_code == 403

    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)
    response = authenticated_client(manager_identity).patch(
        member_url(business, member),
        {"title": "Nouveau titre"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["title"] == "Nouveau titre"
    member.refresh_from_db()
    assert member.title == "Nouveau titre"


def test_legacy_manager_without_permission_cannot_update_title():
    business, owner_identity, owner = create_business_with_owner("title-legacy")
    manager_identity, manager = create_member(
        business,
        "title-legacy-manager",
        role=BusinessMember.Role.MANAGER,
    )
    _, member = create_member(business, "title-legacy-target")

    response = authenticated_client(manager_identity).patch(
        member_url(business, member),
        {"title": "Interdit"},
        format="json",
    )

    assert response.status_code == 403
    member.refresh_from_db()
    assert member.title == "Titre title-legacy-target"


def test_suspended_member_cannot_update_title():
    business, owner_identity, owner = create_business_with_owner("title-suspended")
    manager_identity, manager = create_member(business, "title-suspended-actor")
    _, member = create_member(business, "title-suspended-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    manager.status = BusinessMember.Status.SUSPENDED
    manager.save()

    response = authenticated_client(manager_identity).patch(
        member_url(business, member),
        {"title": "Interdit"},
        format="json",
    )

    assert response.status_code == 403
    member.refresh_from_db()
    assert member.title == "Titre title-suspended-target"


def test_owner_can_suspend_member_and_access_is_blocked_immediately():
    business, owner_identity, owner = create_business_with_owner("suspend-owner")
    _, member = create_member(business, "suspend-target")
    grant_permission(owner, member, Permission.USE_POS)

    response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == BusinessMember.Status.SUSPENDED
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.SUSPENDED
    assert member.suspended_at is not None
    assert member.suspended_by == owner.identity
    assert member.permissions.filter(
        permission=Permission.USE_POS,
    ).exists()

    from apps.businesses.permissions import has_permission

    assert not has_permission(member, Permission.USE_POS)
    assert authenticated_client(member.identity).get(
        f"/api/v1/businesses/{business.public_id}/members/"
    ).status_code == 403


def test_suspension_is_idempotent():
    business, owner_identity, owner = create_business_with_owner("suspend-idempotent")
    _, member = create_member(business, "suspend-idempotent-target")
    grant_permission(owner, member, Permission.USE_POS)

    first = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    second = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["status"] == BusinessMember.Status.SUSPENDED
    assert second.data["status"] == BusinessMember.Status.SUSPENDED
    assert BusinessMember.objects.filter(pk=member.pk).count() == 1


def test_owner_cannot_suspend_owner_or_self_suspend():
    business, owner_identity, owner = create_business_with_owner("suspend-owner-protect")
    manager_identity, manager = create_member(business, "suspend-manager-actor")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    owner_suspend = authenticated_client(owner_identity).post(
        f"{member_url(business, owner)}suspend/",
        format="json",
    )
    assert owner_suspend.status_code == 400
    owner.refresh_from_db()
    assert owner.status == BusinessMember.Status.ACTIVE

    manager_self_suspend = authenticated_client(manager_identity).post(
        f"{member_url(business, manager)}suspend/",
        format="json",
    )
    assert manager_self_suspend.status_code == 400
    manager.refresh_from_db()
    assert manager.status == BusinessMember.Status.ACTIVE


def test_manage_members_permission_allows_suspend_and_reactivate():
    business, owner_identity, owner = create_business_with_owner("suspend-manager")
    manager_identity, manager = create_member(business, "suspend-manager-actor")
    _, member = create_member(business, "suspend-manager-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    suspend_response = authenticated_client(manager_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    assert suspend_response.status_code == 200
    assert suspend_response.data["status"] == BusinessMember.Status.SUSPENDED

    reactivate_response = authenticated_client(manager_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.data["status"] == BusinessMember.Status.ACTIVE

    member.refresh_from_db()
    assert member.status == BusinessMember.Status.ACTIVE
    assert member.suspended_at is None
    assert member.suspended_by is None


def test_reactivation_restores_existing_permissions_without_elevation():
    business, owner_identity, owner = create_business_with_owner("reactivate")
    _, member = create_member(business, "reactivate-target")
    grant_permission(owner, member, Permission.USE_POS)

    authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == BusinessMember.Status.ACTIVE
    assert response.data["permissions"] == [Permission.USE_POS]
    member.refresh_from_db()
    assert member.permissions.filter(permission=Permission.USE_POS).exists()
    assert not member.permissions.filter(
        permission=Permission.MANAGE_MEMBERS,
    ).exists()


def test_reactivation_is_idempotent_for_active_member():
    business, owner_identity, owner = create_business_with_owner("reactivate-idempotent")
    _, member = create_member(business, "reactivate-idempotent-target")

    response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == BusinessMember.Status.ACTIVE
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.ACTIVE
    assert member.suspended_at is None


def test_removed_member_cannot_be_reactivated_through_endpoint():
    business, owner_identity, owner = create_business_with_owner("reactivate-removed")
    _, member = create_member(business, "reactivate-removed-target")
    remove_member(owner, member)

    response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )

    assert response.status_code == 404
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED


def test_owner_can_logically_remove_member_and_permissions_are_revoked():
    business, owner_identity, owner = create_business_with_owner("remove-owner")
    _, member = create_member(business, "remove-target")
    grant_permission(owner, member, Permission.USE_POS)
    grant_permission(owner, member, Permission.VIEW_CATALOG)

    response = authenticated_client(owner_identity).delete(
        member_url(business, member),
    )

    assert response.status_code == 204
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED
    assert member.removed_at is not None
    assert member.removed_by == owner.identity
    assert not member.permissions.exists()
    assert authenticated_client(owner_identity).get(
        member_url(business, member),
    ).status_code == 404


def test_logical_removal_is_idempotent():
    business, owner_identity, owner = create_business_with_owner("remove-idempotent")
    _, member = create_member(business, "remove-idempotent-target")

    first = authenticated_client(owner_identity).delete(
        member_url(business, member),
    )
    second = authenticated_client(owner_identity).delete(
        member_url(business, member),
    )

    assert first.status_code == 204
    assert second.status_code == 204
    assert BusinessMember.objects.filter(pk=member.pk).count() == 1
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED


def test_owner_cannot_be_removed_and_member_cannot_remove_themselves():
    business, owner_identity, owner = create_business_with_owner("remove-protect")
    manager_identity, manager = create_member(business, "remove-manager-actor")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    owner_remove = authenticated_client(owner_identity).delete(
        member_url(business, owner),
    )
    assert owner_remove.status_code == 400
    owner.refresh_from_db()
    assert owner.status == BusinessMember.Status.ACTIVE

    manager_self_remove = authenticated_client(manager_identity).delete(
        member_url(business, manager),
    )
    assert manager_self_remove.status_code == 400
    manager.refresh_from_db()
    assert manager.status == BusinessMember.Status.ACTIVE


def test_manage_members_permission_allows_logical_removal():
    business, owner_identity, owner = create_business_with_owner("remove-manager")
    manager_identity, manager = create_member(business, "remove-manager-actor")
    _, member = create_member(business, "remove-manager-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    response = authenticated_client(manager_identity).delete(
        member_url(business, member),
    )

    assert response.status_code == 204
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED
    assert member.removed_by == manager.identity
    assert not member.permissions.exists()


def test_member_lifecycle_requires_existing_member():
    business, owner_identity, owner = create_business_with_owner("lifecycle-404")

    missing_url = (
        f"/api/v1/businesses/{business.public_id}/members/"
        "BM0000000000/"
    )

    assert authenticated_client(owner_identity).patch(
        missing_url,
        {"title": "Inexistant"},
        format="json",
    ).status_code == 404
    assert authenticated_client(owner_identity).post(
        f"{missing_url}suspend/",
        format="json",
    ).status_code == 404
    assert authenticated_client(owner_identity).post(
        f"{missing_url}reactivate/",
        format="json",
    ).status_code == 404
    assert authenticated_client(owner_identity).delete(
        missing_url,
    ).status_code == 404


def test_member_lifecycle_never_crosses_business_boundaries():
    business_a, owner_a_identity, owner_a = create_business_with_owner("lifecycle-a")
    business_b, owner_b_identity, owner_b = create_business_with_owner("lifecycle-b")
    _, member_b = create_member(business_b, "lifecycle-b-target")

    foreign_patch = authenticated_client(owner_a_identity).patch(
        member_url(business_b, member_b),
        {"title": "Interdit"},
        format="json",
    )
    foreign_suspend = authenticated_client(owner_a_identity).post(
        f"{member_url(business_b, member_b)}suspend/",
        format="json",
    )
    foreign_reactivate = authenticated_client(owner_a_identity).post(
        f"{member_url(business_b, member_b)}reactivate/",
        format="json",
    )
    foreign_remove = authenticated_client(owner_a_identity).delete(
        member_url(business_b, member_b),
    )

    assert foreign_patch.status_code == 404
    assert foreign_suspend.status_code == 404
    assert foreign_reactivate.status_code == 404
    assert foreign_remove.status_code == 404
    member_b.refresh_from_db()
    assert member_b.title == "Titre lifecycle-b-target"
    assert member_b.status == BusinessMember.Status.ACTIVE


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_member_lifecycle_is_blocked_for_inactive_business(business_status):
    business, owner_identity, owner = create_business_with_owner(
        f"lifecycle-inactive-{business_status}"
    )
    _, member = create_member(business, "lifecycle-inactive-target")
    business.status = business_status
    business.save()

    patch = authenticated_client(owner_identity).patch(
        member_url(business, member),
        {"title": "Interdit"},
        format="json",
    )
    suspend = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    reactivate = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )
    remove = authenticated_client(owner_identity).delete(
        member_url(business, member),
    )

    assert patch.status_code == 403
    assert suspend.status_code == 403
    assert reactivate.status_code == 403
    assert remove.status_code == 403
    member.refresh_from_db()
    assert member.title == "Titre lifecycle-inactive-target"
    assert member.status == BusinessMember.Status.ACTIVE


def test_member_lifecycle_query_count_is_constant_as_dataset_grows():
    small_business, small_identity, small_owner = create_business_with_owner(
        "lifecycle-queries-small"
    )
    large_business, large_identity, large_owner = create_business_with_owner(
        "lifecycle-queries-large"
    )
    for index in range(2):
        create_member(small_business, f"lifecycle-queries-small-{index}")
    for index in range(40):
        create_member(large_business, f"lifecycle-queries-large-{index}")
    _, small_target = create_member(small_business, "lifecycle-queries-small-target")
    _, large_target = create_member(large_business, "lifecycle-queries-large-target")

    with CaptureQueriesContext(connection) as small_queries:
        small_response = authenticated_client(small_identity).post(
            f"{member_url(small_business, small_target)}suspend/",
            format="json",
        )
    with CaptureQueriesContext(connection) as large_queries:
        large_response = authenticated_client(large_identity).post(
            f"{member_url(large_business, large_target)}suspend/",
            format="json",
        )

    assert small_response.status_code == 200
    assert large_response.status_code == 200
    assert len(small_queries) == len(large_queries)
    assert len(large_queries) <= 25


def test_concurrent_lifecycle_operations_are_serialized():
    business, owner_identity, owner = create_business_with_owner("lifecycle-concurrent")
    _, member = create_member(business, "lifecycle-concurrent-target")

    first = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    second = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    reactivate = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )
    remove = authenticated_client(owner_identity).delete(
        member_url(business, member),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert reactivate.status_code == 200
    assert remove.status_code == 204
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED
    assert member.suspended_at is None
    assert member.suspended_by is None
    assert member.removed_at is not None


def test_lifecycle_payloads_never_expose_internal_ids_or_identity():
    business, owner_identity, owner = create_business_with_owner("lifecycle-payload")
    _, member = create_member(business, "lifecycle-payload-target")

    suspend_response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    reactivate_response = authenticated_client(owner_identity).post(
        f"{member_url(business, member)}reactivate/",
        format="json",
    )
    patch_response = authenticated_client(owner_identity).patch(
        member_url(business, member),
        {"title": "Caissier"},
        format="json",
    )

    for response in (suspend_response, reactivate_response, patch_response):
        assert response.status_code == 200
        assert set(response.data) == {
            "public_id",
            "title",
            "is_owner",
            "status",
            "permissions",
            "joined_at",
        }
        assert all(row.startswith("BM") for row in [response.data["public_id"]])
        payload = json.dumps(response.data)
        assert str(member.identity_id) not in payload
        assert str(business.id) not in payload
