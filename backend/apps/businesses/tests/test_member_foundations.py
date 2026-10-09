import re

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberPermission,
)
from apps.businesses.permissions import has_permission, membership_for, require_permission
from apps.businesses.services import grant_permission, remove_member


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def member_context():
    business = Business.objects.create(name="Member foundations")
    owner_identity = CarriIdentity.objects.create(carri_subject="foundation-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="foundation-manager")
    member_identity = CarriIdentity.objects.create(carri_subject="foundation-member")
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
    member = BusinessMember.objects.create(
        business=business,
        identity=member_identity,
        title="Caissier",
    )
    return business, owner, manager, member


def test_business_members_receive_unique_public_ids():
    _, owner, manager, member = member_context()

    public_ids = {owner.public_id, manager.public_id, member.public_id}
    assert len(public_ids) == 3
    assert all(re.fullmatch(r"BM[23456789A-HJ-NP-Z]{10}", value) for value in public_ids)


def test_logical_removal_revokes_permissions_and_access_immediately():
    business, owner, _, member = member_context()
    grant_permission(owner, member, Permission.USE_POS)

    removed = remove_member(owner, member)
    removed.refresh_from_db()

    assert removed.status == BusinessMember.Status.REMOVED
    assert removed.removed_at is not None
    assert removed.removed_by == owner.identity
    assert not removed.permissions.exists()
    assert not has_permission(removed, Permission.USE_POS)
    assert membership_for(removed.identity, business) is None
    assert membership_for(
        removed.identity,
        business,
        include_suspended=True,
    ) is None
    with pytest.raises(NotFound):
        require_permission(removed.identity, business, Permission.USE_POS)

    client = APIClient()
    client.force_authenticate(user=removed.identity)
    assert client.get(f"/api/v1/businesses/{business.public_id}/").status_code == 404


def test_manage_members_permission_allows_removing_another_member_only():
    _, owner, manager, member = member_context()
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    remove_member(manager, member)
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.REMOVED

    with pytest.raises(ValidationError, match="cannot remove themselves"):
        remove_member(manager, manager)


def test_owner_and_physical_deletion_are_protected():
    _, owner, _, member = member_context()

    with pytest.raises(ValidationError, match="owner cannot be removed"):
        remove_member(owner, owner)

    owner.status = BusinessMember.Status.REMOVED
    with pytest.raises(ValidationError, match="retain an active owner"):
        owner.save()

    with pytest.raises(ValidationError, match="removed logically"):
        member.delete()

    owner.refresh_from_db()
    member.refresh_from_db()
    assert owner.status == BusinessMember.Status.ACTIVE
    assert member.status == BusinessMember.Status.ACTIVE


def test_removed_membership_keeps_uniqueness_and_removal_is_idempotent():
    business, owner, _, member = member_context()

    first = remove_member(owner, member)
    second = remove_member(owner, member)

    assert first.pk == second.pk
    assert BusinessMember.objects.filter(
        business=business,
        identity=member.identity,
    ).count() == 1
    member.refresh_from_db()
    member.status = BusinessMember.Status.ACTIVE
    with pytest.raises(ValidationError, match="cannot be reactivated"):
        member.save()
    with pytest.raises(ValidationError):
        BusinessMember.objects.create(
            business=business,
            identity=member.identity,
            title="Duplicate",
        )
