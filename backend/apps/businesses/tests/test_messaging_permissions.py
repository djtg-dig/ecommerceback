import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import NotFound
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import (
    has_messaging_permission,
    require_messaging_permission,
)
from apps.businesses.services import grant_permission, remove_member
from apps.businesses.services.invitations import _validated_permissions


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission
MESSAGING_PERMISSIONS = (
    Permission.MESSAGING_VIEW,
    Permission.MESSAGING_REPLY,
    Permission.MESSAGING_ASSIGN,
    Permission.MESSAGING_MANAGE,
)


def membership(business, subject, *, owner=False):
    identity = CarriIdentity.objects.create(carri_subject=subject)
    member = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=BusinessMember.Role.OWNER if owner else BusinessMember.Role.EMPLOYEE,
        title="Gérant" if owner else "Support",
    )
    return identity, member


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def permissions_url(business, member):
    return f"/api/v1/businesses/{business.public_id}/members/{member.public_id}/permissions/"


def test_owner_has_all_messaging_permissions_and_member_has_none_by_default():
    business = Business.objects.create(name="Messaging defaults")
    _, owner = membership(business, "messaging-owner", owner=True)
    _, member = membership(business, "messaging-member")

    for permission in MESSAGING_PERMISSIONS:
        assert has_messaging_permission(owner, permission)
        assert not has_messaging_permission(member, permission)
    assert not member.permissions.exists()


def test_owner_can_grant_each_messaging_permission_through_the_api():
    business = Business.objects.create(name="Messaging grants")
    owner_identity, owner = membership(business, "messaging-grant-owner", owner=True)
    _, member = membership(business, "messaging-grant-member")
    client = client_for(owner_identity)

    for permission in MESSAGING_PERMISSIONS:
        response = client.post(
            permissions_url(business, member),
            {"permission": permission},
            format="json",
        )
        assert response.status_code == 201

    assert set(
        member.permissions.values_list("permission", flat=True)
    ) == set(MESSAGING_PERMISSIONS)


def test_dependent_messaging_permission_requires_view_and_view_revoke_cascades():
    business = Business.objects.create(name="Messaging dependencies")
    owner_identity, owner = membership(business, "messaging-dependency-owner", owner=True)
    _, member = membership(business, "messaging-dependency-member")
    client = client_for(owner_identity)

    rejected = client.post(
        permissions_url(business, member),
        {"permission": Permission.MESSAGING_REPLY},
        format="json",
    )
    assert rejected.status_code == 400
    assert not member.permissions.exists()

    grant_permission(owner, member, Permission.MESSAGING_VIEW)
    for permission in MESSAGING_PERMISSIONS[1:]:
        grant_permission(owner, member, permission)

    response = client.delete(
        f"{permissions_url(business, member)}{Permission.MESSAGING_VIEW}/"
    )
    assert response.status_code == 204
    assert not member.permissions.filter(permission__in=MESSAGING_PERMISSIONS).exists()


def test_messaging_permissions_are_inert_for_suspended_and_removed_members():
    business = Business.objects.create(name="Messaging inactive")
    _, owner = membership(business, "messaging-inactive-owner", owner=True)
    _, suspended = membership(business, "messaging-suspended")
    _, removed = membership(business, "messaging-removed")
    grant_permission(owner, suspended, Permission.MESSAGING_VIEW)
    grant_permission(owner, removed, Permission.MESSAGING_VIEW)

    suspended.status = BusinessMember.Status.SUSPENDED
    suspended.save()
    removed.status = BusinessMember.Status.REMOVED
    removed.save()

    assert not has_messaging_permission(suspended, Permission.MESSAGING_VIEW)
    assert not has_messaging_permission(removed, Permission.MESSAGING_VIEW)


def test_messaging_permission_is_scoped_to_one_business():
    business_a = Business.objects.create(name="Messaging A")
    business_b = Business.objects.create(name="Messaging B")
    identity, owner_a = membership(business_a, "messaging-a-owner", owner=True)
    membership(business_b, "messaging-b-owner", owner=True)

    assert require_messaging_permission(
        identity,
        business_a,
        Permission.MESSAGING_VIEW,
    ) == owner_a
    with pytest.raises(NotFound):
        require_messaging_permission(
            identity,
            business_b,
            Permission.MESSAGING_VIEW,
        )


def test_unauthorized_actor_and_owner_mutation_are_rejected():
    business = Business.objects.create(name="Messaging administration")
    owner_identity, owner = membership(business, "messaging-admin-owner", owner=True)
    actor_identity, actor = membership(business, "messaging-admin-actor")
    _, target = membership(business, "messaging-admin-target")

    unauthorized = client_for(actor_identity).post(
        permissions_url(business, target),
        {"permission": Permission.MESSAGING_VIEW},
        format="json",
    )
    owner_mutation = client_for(owner_identity).delete(
        f"{permissions_url(business, owner)}{Permission.MESSAGING_VIEW}/"
    )

    assert unauthorized.status_code == 403
    assert owner_mutation.status_code == 400
    assert not target.permissions.exists()


def test_messaging_grant_preserves_existing_permissions_and_rejects_bad_payload():
    business = Business.objects.create(name="Messaging compatibility")
    owner_identity, owner = membership(business, "messaging-compatible-owner", owner=True)
    _, member = membership(business, "messaging-compatible-member")
    grant_permission(owner, member, Permission.PRODUCT_VIEW)
    client = client_for(owner_identity)

    assert client.post(
        permissions_url(business, member),
        {"permission": Permission.MESSAGING_VIEW},
        format="json",
    ).status_code == 201
    assert client.post(
        permissions_url(business, member),
        {"permission": "messaging.view"},
        format="json",
    ).status_code == 400
    assert member.permissions.filter(permission=Permission.PRODUCT_VIEW).exists()


def test_invitation_permissions_enforce_messaging_dependencies():
    with pytest.raises(ValidationError, match="MESSAGING_REPLY requires MESSAGING_VIEW"):
        _validated_permissions([Permission.MESSAGING_REPLY])

    assert _validated_permissions([
        Permission.MESSAGING_VIEW,
        Permission.MESSAGING_REPLY,
    ]) == [Permission.MESSAGING_VIEW, Permission.MESSAGING_REPLY]


def test_removed_member_loses_persisted_messaging_permissions():
    business = Business.objects.create(name="Messaging removal")
    _, owner = membership(business, "messaging-removal-owner", owner=True)
    _, member = membership(business, "messaging-removal-member")
    grant_permission(owner, member, Permission.MESSAGING_VIEW)

    remove_member(owner, member)

    assert not member.permissions.exists()
