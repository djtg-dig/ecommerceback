from importlib import import_module
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import (
    has_permission,
    membership_for,
    require_any_permission,
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

    from apps.businesses.permissions import atomic_permission_values

    for permission in atomic_permission_values():
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

    assert not has_permission(member, Permission.SALE_CREATE)
    with pytest.raises(PermissionDenied):
        require_permission(member_identity, business, Permission.SALE_CREATE)


@pytest.mark.django_db
def test_any_permission_gate_accepts_one_explicit_right_and_rejects_unknown():
    business, _, member_identity, owner, member = create_memberships()

    with pytest.raises(PermissionDenied):
        require_any_permission(
            member_identity,
            business,
            (Permission.PAYMENT_METHOD_VIEW, Permission.SALE_CREATE),
        )

    grant_permission(owner, member, Permission.SALE_CREATE)
    assert require_any_permission(
        member_identity,
        business,
        (Permission.PAYMENT_METHOD_VIEW, Permission.SALE_CREATE),
    ) == member

    with pytest.raises(ValidationError, match="Unknown Business permission"):
        require_any_permission(
            member_identity,
            business,
            (Permission.SALE_CREATE, "CLIENT_PERMISSION"),
        )

    grant_permission(owner, member, Permission.SALE_CREATE)
    assert require_permission(member_identity, business, Permission.SALE_CREATE) == member

    revoke_permission(owner, member, Permission.SALE_CREATE)
    with pytest.raises(PermissionDenied):
        require_permission(member_identity, business, Permission.SALE_CREATE)


@pytest.mark.django_db
def test_titles_and_legacy_roles_never_grant_implicit_permissions():
    business, _, member_identity, owner, member = create_memberships()

    assert member.role == BusinessMember.Role.MANAGER
    assert member.title == "Gestionnaire"
    assert not has_permission(member, Permission.MEMBER_PERMISSION_GRANT)

    member.role = BusinessMember.Role.EMPLOYEE
    member.title = "Employé"
    member.save()
    grant_permission(owner, member, Permission.MEMBER_PERMISSION_GRANT)

    assert require_permission(
        member_identity,
        business,
        Permission.MEMBER_PERMISSION_GRANT,
    ) == member


@pytest.mark.django_db
def test_suspended_member_has_no_access_and_receives_403():
    business, _, member_identity, owner, member = create_memberships()
    grant_permission(owner, member, Permission.PRODUCT_VIEW)
    member.status = BusinessMember.Status.SUSPENDED
    member.save()

    assert membership_for(member_identity, business) is None
    assert membership_for(
        member_identity,
        business,
        include_suspended=True,
    ) == member
    assert not has_permission(member, Permission.PRODUCT_VIEW)
    with pytest.raises(PermissionDenied) as error:
        require_permission(member_identity, business, Permission.PRODUCT_VIEW)

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
        Permission.MEMBER_VIEW,
    ) == owner
    with pytest.raises(PermissionDenied):
        require_permission(
            owner_identity,
            business,
            Permission.MEMBER_PERMISSION_GRANT,
            write=True,
        )
    with pytest.raises(ValidationError, match="authorized active member"):
        grant_permission(owner, member, Permission.PRODUCT_VIEW)


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
        require_permission(outsider, business, Permission.MEMBER_VIEW)
    assert error.value.status_code == 404

    with pytest.raises(ValidationError, match="authorized active member"):
        grant_permission(other_owner, member, Permission.SALE_CREATE)
    assert not member.permissions.exists()


@pytest.mark.django_db
def test_non_owner_cannot_self_assign_or_revoke_permissions():
    _, _, _, owner, member = create_memberships()
    grant_permission(owner, member, Permission.SALE_CREATE)

    with pytest.raises(ValidationError, match="authorized active member"):
        grant_permission(member, member, Permission.MEMBER_PERMISSION_GRANT)
    with pytest.raises(ValidationError, match="authorized active member"):
        revoke_permission(member, member, Permission.SALE_CREATE)

    assert member.permissions.filter(permission=Permission.SALE_CREATE).exists()
    assert not member.permissions.filter(permission=Permission.MEMBER_PERMISSION_GRANT).exists()


@pytest.mark.django_db
def test_owner_implicit_rights_cannot_be_granted_or_revoked():
    _, _, _, owner, _ = create_memberships()

    with pytest.raises(ValidationError, match="already have all permissions"):
        grant_permission(owner, owner, Permission.SALE_CREATE)
    with pytest.raises(ValidationError, match="cannot be revoked"):
        revoke_permission(owner, owner, Permission.SALE_CREATE)

    assert has_permission(owner, Permission.SALE_CREATE)
    assert not owner.permissions.exists()


@pytest.mark.django_db
def test_grant_and_revoke_reject_unknown_permissions():
    _, _, _, owner, member = create_memberships()

    with pytest.raises(ValidationError, match="Unknown Business permission"):
        grant_permission(owner, member, "UNKNOWN")
    with pytest.raises(ValidationError, match="Unknown Business permission"):
        revoke_permission(owner, member, "UNKNOWN")


def test_invitation_permission_migration_expands_known_and_drops_unknown_codes():
    invitation = SimpleNamespace(
        pk="invitation-1",
        permissions=["VIEW_CATALOG", "PRODUCT_DELETE", "UNKNOWN_PERMISSION"],
        saved_fields=None,
    )

    class QuerySet(list):
        def only(self, *_fields):
            return self

    class Manager:
        def filter(self, **_filters):
            return []

        def all(self):
            return QuerySet([invitation])

    class FakePermissionModel:
        objects = Manager()

    class FakeInvitationModel:
        objects = Manager()

    def save(*, update_fields):
        invitation.saved_fields = update_fields

    invitation.save = save

    class HistoricalApps:
        def get_model(self, app_label, model_name):
            assert app_label == "businesses"
            return FakePermissionModel if model_name == "BusinessMemberPermission" else FakeInvitationModel

    migration = import_module("apps.businesses.migrations.0012_expand_atomic_permissions")
    migration.forwards(HistoricalApps(), None)

    assert invitation.permissions == [
        "VIEW_CATALOG",
        "PRODUCT_VIEW",
        "PRODUCT_VARIANT_VIEW",
        "PRODUCT_DELETE",
    ]
    assert invitation.saved_fields == ("permissions",)
