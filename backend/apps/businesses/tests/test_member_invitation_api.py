import re

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberInvitation,
    BusinessMemberPermission,
)
from apps.businesses.services import grant_permission, remove_member
from apps.businesses.services.invitations import (
    generate_invitation_token,
    hash_invitation_token,
    invite_member,
    normalize_email,
)


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def create_business_with_owner(suffix):
    business = Business.objects.create(name=f"Invitations {suffix}")
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


def test_owner_creates_invitation_with_normalized_email_and_hashed_token():
    business, owner_identity, owner = create_business_with_owner("create")

    invitation, token = invite_member(
        owner,
        business,
        " Invitee@Example.COM ",
        title="Caissier",
    )

    assert invitation.status == BusinessMemberInvitation.Status.PENDING
    assert invitation.email == "invitee@example.com"
    assert invitation.normalized_email == "invitee@example.com"
    assert invitation.title == "Caissier"
    assert invitation.business == business
    assert invitation.invited_by == owner.identity
    assert invitation.member is None
    assert invitation.accepted_by is None
    assert invitation.acted_at is None
    assert invitation.last_sent_at is not None
    assert invitation.resend_count == 0
    assert invitation.public_id.startswith("MI")
    assert re.fullmatch(r"MI[23456789A-HJ-NP-Z]{10}", invitation.public_id)
    assert len(invitation.token_hash) == 64
    assert invitation.token_hash == hash_invitation_token(token)
    assert token not in invitation.token_hash
    assert not BusinessMember.objects.filter(
        business=business,
        identity__carri_subject="invitee@example.com",
    ).exists()


def test_invitation_public_ids_are_unique():
    business, owner_identity, owner = create_business_with_owner("unique")

    first, _ = invite_member(owner, business, "first@example.com")
    second, _ = invite_member(owner, business, "second@example.com")

    assert first.public_id != second.public_id
    assert BusinessMemberInvitation.objects.filter(
        public_id=first.public_id,
    ).count() == 1


def test_duplicate_pending_invitation_is_rejected():
    business, owner_identity, owner = create_business_with_owner("duplicate")

    first, _ = invite_member(owner, business, "dup@example.com")

    with pytest.raises(ValidationError, match="pending invitation"):
        invite_member(owner, business, "dup@example.com")

    assert BusinessMemberInvitation.objects.filter(
        business=business,
        normalized_email="dup@example.com",
        status=BusinessMemberInvitation.Status.PENDING,
    ).count() == 1
    assert first.pk in BusinessMemberInvitation.objects.values_list(
        "pk",
        flat=True,
    )


def test_email_normalization_is_deterministic():
    business, owner_identity, owner = create_business_with_owner("normalize")

    assert normalize_email("  Mixed.Case@Example.COM  ") == "mixed.case@example.com"
    assert normalize_email("") == ""
    assert normalize_email(None) == ""

    invitation, _ = invite_member(owner, business, "  Spaced@Example.COM ")

    assert invitation.normalized_email == "spaced@example.com"


def test_expired_pending_invitation_is_expired_before_recreation():
    business, owner_identity, owner = create_business_with_owner("expire")

    first, _ = invite_member(owner, business, "stale@example.com")
    first.expires_at = timezone.now() - timezone.timedelta(hours=1)
    first.save(update_fields=("expires_at",))

    second, _ = invite_member(owner, business, "stale@example.com")

    first.refresh_from_db()
    assert first.status == BusinessMemberInvitation.Status.EXPIRED
    assert first.acted_at is not None
    assert second.status == BusinessMemberInvitation.Status.PENDING
    assert second.pk != first.pk


def test_invitation_requires_manage_members_permission():
    business, owner_identity, owner = create_business_with_owner("permission")
    employee_identity, employee = create_member(business, "employee")

    with pytest.raises(ValidationError, match="authorized member manager"):
        invite_member(employee, business, "noperm@example.com")

    grant_permission(owner, employee, Permission.MANAGE_MEMBERS)
    invitation, _ = invite_member(employee, business, "granted@example.com")

    assert invitation.status == BusinessMemberInvitation.Status.PENDING
    assert invitation.invited_by == employee.identity


def test_legacy_manager_without_permission_cannot_invite():
    business, owner_identity, owner = create_business_with_owner("legacy")
    manager_identity, manager = create_member(
        business,
        "legacy-manager",
        role=BusinessMember.Role.MANAGER,
    )

    with pytest.raises(ValidationError, match="authorized member manager"):
        invite_member(manager, business, "legacy@example.com")

    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_suspended_member_cannot_invite():
    business, owner_identity, owner = create_business_with_owner("suspended")
    manager_identity, manager = create_member(business, "suspended-manager")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    manager.status = BusinessMember.Status.SUSPENDED
    manager.save()

    with pytest.raises(ValidationError, match="active member"):
        invite_member(manager, business, "suspended@example.com")

    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_removed_member_cannot_invite():
    business, owner_identity, owner = create_business_with_owner("removed")
    manager_identity, manager = create_member(business, "removed-manager")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    remove_member(owner, manager)

    with pytest.raises(ValidationError, match="authorized member manager"):
        invite_member(manager, business, "removed@example.com")

    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_inactive_business_cannot_invite():
    business, owner_identity, owner = create_business_with_owner("inactive")
    business.status = Business.Status.SUSPENDED
    business.save()

    with pytest.raises(ValidationError, match="active Business"):
        invite_member(owner, business, "inactive@example.com")

    business.status = Business.Status.ARCHIVED
    business.save()

    with pytest.raises(ValidationError, match="active Business"):
        invite_member(owner, business, "archived@example.com")

    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_existing_membership_blocks_invitation():
    business, owner_identity, owner = create_business_with_owner("existing")
    active_identity, active = create_member(business, "active-target")
    suspended_identity, suspended = create_member(business, "suspended-target")
    suspended.status = BusinessMember.Status.SUSPENDED
    suspended.save()

    with pytest.raises(ValidationError, match="already has a Business membership"):
        invite_member(owner, business, active.identity.carri_subject)
    with pytest.raises(ValidationError, match="already has a Business membership"):
        invite_member(owner, business, suspended.identity.carri_subject)

    assert not BusinessMemberInvitation.objects.filter(
        business=business,
    ).exists()


def test_invitation_never_crosses_business_boundaries():
    business_a, owner_a_identity, owner_a = create_business_with_owner("tenant-a")
    business_b, owner_b_identity, owner_b = create_business_with_owner("tenant-b")

    with pytest.raises(ValidationError, match="inside one Business"):
        invite_member(owner_a, business_b, "foreign@example.com")

    assert not BusinessMemberInvitation.objects.filter(
        business=business_b,
    ).exists()


def test_invitation_token_is_unpredictable_and_not_stored_in_clear():
    business, owner_identity, owner = create_business_with_owner("token")

    first, first_token = invite_member(owner, business, "token-one@example.com")
    second, second_token = invite_member(owner, business, "token-two@example.com")

    assert first_token != second_token
    assert len(first_token) >= 32
    assert first.token_hash == hash_invitation_token(first_token)
    assert second.token_hash == hash_invitation_token(second_token)
    assert first_token not in first.token_hash
    assert generate_invitation_token() != generate_invitation_token()


def test_invitation_does_not_create_membership_or_permissions():
    business, owner_identity, owner = create_business_with_owner("no-membership")

    invitation, _ = invite_member(owner, business, "invitee@example.com")

    assert invitation.member is None
    assert not BusinessMember.objects.filter(
        business=business,
        identity__carri_subject="invitee@example.com",
    ).exists()
    assert not BusinessMember.objects.filter(
        business=business,
    ).exclude(pk=owner.pk).exists()


def test_concurrent_invitation_creation_is_serialized():
    business, owner_identity, owner = create_business_with_owner("concurrent")

    first, _ = invite_member(owner, business, "race@example.com")

    with pytest.raises(ValidationError, match="pending invitation"):
        invite_member(owner, business, "race@example.com")

    assert BusinessMemberInvitation.objects.filter(
        business=business,
        normalized_email="race@example.com",
    ).count() == 1
    assert first.status == BusinessMemberInvitation.Status.PENDING


def test_invitation_expiry_state_is_derived():
    business, owner_identity, owner = create_business_with_owner("state")

    invitation, _ = invite_member(owner, business, "state@example.com")
    assert invitation.is_expired is False

    invitation.expires_at = timezone.now() - timezone.timedelta(hours=1)
    assert invitation.is_expired is True

    from apps.businesses.services.invitations import validate_invitation_state

    assert validate_invitation_state(invitation) == (
        BusinessMemberInvitation.Status.EXPIRED
    )

    fresh, _ = invite_member(owner, business, "fresh@example.com")
    assert validate_invitation_state(fresh) == (
        BusinessMemberInvitation.Status.PENDING
    )


def test_invitation_title_defaults_to_empty_and_owner_cannot_be_invited():
    business, owner_identity, owner = create_business_with_owner("title")

    invitation, _ = invite_member(owner, business, "titled@example.com")

    assert invitation.title == ""

    with pytest.raises(ValidationError, match="already has a Business membership"):
        invite_member(owner, business, owner.identity.carri_subject)
