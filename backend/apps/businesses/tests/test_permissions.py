import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import (
    has_permission,
    membership_for,
    require_permission,
)
from apps.businesses.services import grant_permission, revoke_permission


Permission = BusinessMemberPermission.Permission


def create_memberships():
    business = Business.objects.create(name="Permission engine")
    owner_identity = CarriIdentity.objects.create(carri_subject="engine-owner")
    member_identity = CarriIdentity.objects.create(carri_subject="engine-member")
    owner = BusinessMember.objects.create(
        business=business,
        identity=owner_identity,
        role=BusinessMember.Role.OWNER,
        is_owner=True,
        title="Gérant",
    )
    member = BusinessMember.objects.create(
        business=business,
        identity=member_identity,
        role=BusinessMember.Role.MANAGER,
        title="Gestionnaire",
    )

    return business, owner_identity, member_identity, owner, member


@pytest.mark.django_db
def test_owner_has_every_registered_permission_but_unknown_is_rejected():
    business, owner_identity, _, owner, _ = create_memberships()

    for permission in Permission.values:
        assert has_permission(owner, permission)
        assert require_permission(owner_identity, business, permission) == owner

    with pytest.raises(ValidationError, match="Unknown Business permission"):
        has_permission(owner, "CLIENT_SUPPLIED_PERMISSION")
    with pytest.raises(ValidationError, match="Unknown Business permission"):
        require_permission(
            owner_identity,
            business,
            "CLIENT_SUPPLIED_PERMISSION",
        )


@pytest.mark.django_db
def test_individual_permission_can_be_granted_required_and_revoked():
    business, _, member_identity, owner, member = create_memberships()

    assert not has_permission(member, Permission.USE_POS)
    with pytest.raises(PermissionDenied):
        require_permission(member_identity, business, Permission.USE_POS)

    grant_permission(owner, member, Permission.USE_POS)
    assert require_permission(member_identity, business, Permission.USE_POS) == member

    revoke_permission(owner, member, Permission.USE_POS)
    with pytest.raises(PermissionDenied):
        require_permission(member_identity, business, Permission.USE_POS)


@pytest.mark.django_db
def test_titles_and_legacy_roles_never_grant_implicit_permissions():
    business, _, member_identity, owner, member = create_memberships()

    assert member.role == BusinessMember.Role.MANAGER
    assert member.title == "Gestionnaire"
    assert not has_permission(member, Permission.MANAGE_MEMBERS)

    member.role = BusinessMember.Role.EMPLOYEE
    member.title = "Employé"
    member.save()
    grant_permission(owner, member, Permission.MANAGE_MEMBERS)

    assert require_permission(
        member_identity,
        business,
        Permission.MANAGE_MEMBERS,
    ) == member


@pytest.mark.django_db
def test_suspended_member_has_no_access_and_receives_403():
    business, _, member_identity, owner, member = create_memberships()
    grant_permission(owner, member, Permission.VIEW_CATALOG)
    member.status = BusinessMember.Status.SUSPENDED
    member.save()

    assert membership_for(member_identity, business) is None
    assert membership_for(
        member_identity,
        business,
        include_suspended=True,
    ) == member
    assert not has_permission(member, Permission.VIEW_CATALOG)
    with pytest.raises(PermissionDenied) as error:
        require_permission(member_identity, business, Permission.VIEW_CATALOG)

    assert error.value.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("business_status", [Business.Status.SUSPENDED, Business.Status.ARCHIVED])
def test_inactive_business_allows_authorized_read_but_blocks_writes(business_status):
    business, owner_identity, _, owner, member = create_memberships()
    business.status = business_status
    business.save()

    assert require_permission(
        owner_identity,
        business,
        Permission.VIEW_MEMBERS,
    ) == owner
    with pytest.raises(PermissionDenied):
        require_permission(
            owner_identity,
            business,
            Permission.MANAGE_MEMBERS,
            write=True,
        )
    with pytest.raises(ValidationError, match="inactive Business"):
        grant_permission(owner, member, Permission.VIEW_CATALOG)


@pytest.mark.django_db
def test_missing_membership_is_404_and_never_crosses_businesses():
    business, _, _, _, member = create_memberships()
    outsider = CarriIdentity.objects.create(carri_subject="engine-outsider")
    other_business = Business.objects.create(name="Other permission tenant")
    other_owner = BusinessMember.objects.create(
        business=other_business,
        identity=outsider,
        role=BusinessMember.Role.OWNER,
        is_owner=True,
        title="Gérant",
    )

    with pytest.raises(NotFound) as error:
        require_permission(outsider, business, Permission.VIEW_MEMBERS)
    assert error.value.status_code == 404

    with pytest.raises(ValidationError, match="active Business owner"):
        grant_permission(other_owner, member, Permission.USE_POS)
    assert not member.permissions.exists()


@pytest.mark.django_db
def test_non_owner_cannot_self_assign_or_revoke_permissions():
    _, _, _, owner, member = create_memberships()
    grant_permission(owner, member, Permission.USE_POS)

    with pytest.raises(ValidationError, match="active Business owner"):
        grant_permission(member, member, Permission.MANAGE_MEMBERS)
    with pytest.raises(ValidationError, match="active Business owner"):
        revoke_permission(member, member, Permission.USE_POS)

    assert member.permissions.filter(permission=Permission.USE_POS).exists()
    assert not member.permissions.filter(permission=Permission.MANAGE_MEMBERS).exists()


@pytest.mark.django_db
def test_owner_implicit_rights_cannot_be_granted_or_revoked():
    _, _, _, owner, _ = create_memberships()

    with pytest.raises(ValidationError, match="already have all permissions"):
        grant_permission(owner, owner, Permission.USE_POS)
    with pytest.raises(ValidationError, match="cannot be revoked"):
        revoke_permission(owner, owner, Permission.USE_POS)

    assert has_permission(owner, Permission.USE_POS)
    assert not owner.permissions.exists()


@pytest.mark.django_db
def test_grant_and_revoke_reject_unknown_permissions():
    _, _, _, owner, member = create_memberships()

    with pytest.raises(ValidationError, match="Unknown Business permission"):
        grant_permission(owner, member, "UNKNOWN")
    with pytest.raises(ValidationError, match="Unknown Business permission"):
        revoke_permission(owner, member, "UNKNOWN")
