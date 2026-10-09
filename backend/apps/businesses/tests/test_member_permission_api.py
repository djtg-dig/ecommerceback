import pytest
from django.core.exceptions import ValidationError
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
    business = Business.objects.create(name=f"Permissions {suffix}")
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


def permissions_url(business, member):
    return f"{member_url(business, member)}permissions/"


def permission_url(business, member, permission):
    return f"{permissions_url(business, member)}{permission}/"


def catalog_url(business):
    return f"/api/v1/businesses/{business.public_id}/permissions/"


def test_owner_can_grant_and_revoke_permission():
    business, owner_identity, owner = create_business_with_owner("grant-owner")
    _, member = create_member(business, "grant-target")

    grant_response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )

    assert grant_response.status_code == 201
    assert grant_response.data == {"permission": Permission.USE_POS}
    assert member.permissions.filter(permission=Permission.USE_POS).exists()

    revoke_response = authenticated_client(owner_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert revoke_response.status_code == 204
    assert not member.permissions.filter(
        permission=Permission.USE_POS,
    ).exists()


def test_owner_can_read_member_permissions():
    business, owner_identity, owner = create_business_with_owner("read-owner")
    _, member = create_member(business, "read-target")
    grant_permission(owner, member, Permission.USE_POS)
    grant_permission(owner, member, Permission.VIEW_CATALOG)

    response = authenticated_client(owner_identity).get(
        permissions_url(business, member),
    )

    assert response.status_code == 200
    assert response.data == [
        {"permission": Permission.USE_POS},
        {"permission": Permission.VIEW_CATALOG},
    ]


def test_owner_permissions_are_implicit_and_readable():
    business, owner_identity, owner = create_business_with_owner("read-owner-implicit")

    response = authenticated_client(owner_identity).get(
        permissions_url(business, owner),
    )

    assert response.status_code == 200
    assert [row["permission"] for row in response.data] == list(
        Permission.values,
    )
    assert not owner.permissions.exists()


def test_permission_catalog_lists_registered_permissions():
    business, owner_identity, owner = create_business_with_owner("catalog")

    response = authenticated_client(owner_identity).get(catalog_url(business))

    assert response.status_code == 200
    assert [row["permission"] for row in response.data] == list(
        Permission.values,
    )
    assert all(row["label"] for row in response.data)


def test_grant_is_idempotent():
    business, owner_identity, owner = create_business_with_owner("grant-idempotent")
    _, member = create_member(business, "grant-idempotent-target")

    first = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    second = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert member.permissions.filter(permission=Permission.USE_POS).count() == 1


def test_revoke_is_idempotent():
    business, owner_identity, owner = create_business_with_owner("revoke-idempotent")
    _, member = create_member(business, "revoke-idempotent-target")
    grant_permission(owner, member, Permission.USE_POS)

    first = authenticated_client(owner_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )
    second = authenticated_client(owner_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert first.status_code == 204
    assert second.status_code == 204
    assert not member.permissions.filter(permission=Permission.USE_POS).exists()


def test_manage_members_without_ownership_cannot_grant_or_revoke():
    business, owner_identity, owner = create_business_with_owner("grant-manager")
    manager_identity, manager = create_member(business, "grant-manager-actor")
    _, member = create_member(business, "grant-manager-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    grant_response = authenticated_client(manager_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    revoke_response = authenticated_client(manager_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert grant_response.status_code == 403
    assert revoke_response.status_code == 403
    assert not member.permissions.exists()


def test_member_without_permission_cannot_grant_or_revoke():
    business, owner_identity, owner = create_business_with_owner("grant-employee")
    employee_identity, employee = create_member(business, "grant-employee-actor")
    _, member = create_member(business, "grant-employee-target")

    grant_response = authenticated_client(employee_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    revoke_response = authenticated_client(employee_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert grant_response.status_code == 403
    assert revoke_response.status_code == 403
    assert not member.permissions.exists()


def test_legacy_manager_without_permission_cannot_grant():
    business, owner_identity, owner = create_business_with_owner("grant-legacy")
    manager_identity, manager = create_member(
        business,
        "grant-legacy-manager",
        role=BusinessMember.Role.MANAGER,
    )
    _, member = create_member(business, "grant-legacy-target")

    response = authenticated_client(manager_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )

    assert response.status_code == 403
    assert not member.permissions.exists()


def test_suspended_member_cannot_grant_or_revoke():
    business, owner_identity, owner = create_business_with_owner("grant-suspended")
    manager_identity, manager = create_member(business, "grant-suspended-actor")
    _, member = create_member(business, "grant-suspended-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    manager.status = BusinessMember.Status.SUSPENDED
    manager.save()

    grant_response = authenticated_client(manager_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    revoke_response = authenticated_client(manager_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert grant_response.status_code == 403
    assert revoke_response.status_code == 403
    assert not member.permissions.exists()


def test_removed_member_cannot_grant_or_revoke():
    business, owner_identity, owner = create_business_with_owner("grant-removed")
    manager_identity, manager = create_member(business, "grant-removed-actor")
    _, member = create_member(business, "grant-removed-target")
    grant_permission(owner, manager, Permission.MANAGE_MEMBERS)

    remove_member(owner, manager)

    grant_response = authenticated_client(manager_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    revoke_response = authenticated_client(manager_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert grant_response.status_code == 404
    assert revoke_response.status_code == 404
    assert not member.permissions.exists()


def test_owner_cannot_grant_to_owner_or_self():
    business, owner_identity, owner = create_business_with_owner("grant-owner-protect")

    owner_grant = authenticated_client(owner_identity).post(
        permissions_url(business, owner),
        {"permission": Permission.USE_POS},
        format="json",
    )
    owner_revoke = authenticated_client(owner_identity).delete(
        permission_url(business, owner, Permission.USE_POS),
    )

    assert owner_grant.status_code == 400
    assert owner_revoke.status_code == 400
    assert not owner.permissions.exists()


def test_unknown_permission_is_rejected():
    business, owner_identity, owner = create_business_with_owner("grant-unknown")
    _, member = create_member(business, "grant-unknown-target")

    grant_response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": "CLIENT_SUPPLIED_PERMISSION"},
        format="json",
    )
    revoke_response = authenticated_client(owner_identity).delete(
        permission_url(business, member, "CLIENT_SUPPLIED_PERMISSION"),
    )

    assert grant_response.status_code == 400
    assert revoke_response.status_code == 400
    assert not member.permissions.exists()


def test_permission_grant_requires_payload():
    business, owner_identity, owner = create_business_with_owner("grant-empty")
    _, member = create_member(business, "grant-empty-target")

    response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {},
        format="json",
    )

    assert response.status_code == 400
    assert not member.permissions.exists()


def test_permission_mutations_are_blocked_for_inactive_business():
    business, owner_identity, owner = create_business_with_owner("grant-inactive")
    _, member = create_member(business, "grant-inactive-target")
    grant_permission(owner, member, Permission.USE_POS)
    business.status = Business.Status.SUSPENDED
    business.save()

    grant_response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.VIEW_CATALOG},
        format="json",
    )
    revoke_response = authenticated_client(owner_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )

    assert grant_response.status_code == 403
    assert revoke_response.status_code == 403
    assert member.permissions.filter(permission=Permission.USE_POS).exists()
    assert not member.permissions.filter(
        permission=Permission.VIEW_CATALOG,
    ).exists()


def test_permission_administration_never_crosses_business_boundaries():
    business_a, owner_a_identity, owner_a = create_business_with_owner("grant-a")
    business_b, owner_b_identity, owner_b = create_business_with_owner("grant-b")
    _, member_b = create_member(business_b, "grant-b-target")

    foreign_grant = authenticated_client(owner_a_identity).post(
        permissions_url(business_b, member_b),
        {"permission": Permission.USE_POS},
        format="json",
    )
    foreign_revoke = authenticated_client(owner_a_identity).delete(
        permission_url(business_b, member_b, Permission.USE_POS),
    )
    foreign_read = authenticated_client(owner_a_identity).get(
        permissions_url(business_b, member_b),
    )
    foreign_catalog = authenticated_client(owner_a_identity).get(
        catalog_url(business_b),
    )

    assert foreign_grant.status_code == 404
    assert foreign_revoke.status_code == 404
    assert foreign_read.status_code == 404
    assert foreign_catalog.status_code == 404
    assert not member_b.permissions.exists()


def test_permission_read_requires_view_members():
    business, owner_identity, owner = create_business_with_owner("read-gate")
    manager_identity, manager = create_member(business, "read-gate-manager")
    _, member = create_member(business, "read-gate-target")

    assert authenticated_client(manager_identity).get(
        permissions_url(business, member),
    ).status_code == 403
    assert authenticated_client(manager_identity).get(
        catalog_url(business),
    ).status_code == 403

    grant_permission(owner, manager, Permission.VIEW_MEMBERS)

    assert authenticated_client(manager_identity).get(
        permissions_url(business, member),
    ).status_code == 200
    assert authenticated_client(manager_identity).get(
        catalog_url(business),
    ).status_code == 200


def test_permission_read_returns_404_for_removed_member():
    business, owner_identity, owner = create_business_with_owner("read-removed")
    _, member = create_member(business, "read-removed-target")
    grant_permission(owner, member, Permission.USE_POS)
    remove_member(owner, member)

    response = authenticated_client(owner_identity).get(
        permissions_url(business, member),
    )

    assert response.status_code == 404


def test_permission_grant_preserves_existing_permissions():
    business, owner_identity, owner = create_business_with_owner("grant-preserve")
    _, member = create_member(business, "grant-preserve-target")
    grant_permission(owner, member, Permission.USE_POS)

    response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.VIEW_CATALOG},
        format="json",
    )

    assert response.status_code == 201
    assert member.permissions.filter(permission=Permission.USE_POS).exists()
    assert member.permissions.filter(permission=Permission.VIEW_CATALOG).exists()


def test_suspended_member_keeps_permissions_but_cannot_use_them():
    business, owner_identity, owner = create_business_with_owner("suspend-perms")
    _, member = create_member(business, "suspend-perms-target")
    grant_permission(owner, member, Permission.USE_POS)

    authenticated_client(owner_identity).post(
        f"{member_url(business, member)}suspend/",
        format="json",
    )
    member.refresh_from_db()

    assert member.permissions.filter(permission=Permission.USE_POS).exists()
    from apps.businesses.permissions import has_permission

    assert not has_permission(member, Permission.USE_POS)


def test_removed_member_permissions_are_not_restored():
    business, owner_identity, owner = create_business_with_owner("remove-perms")
    _, member = create_member(business, "remove-perms-target")
    grant_permission(owner, member, Permission.USE_POS)

    remove_member(owner, member)
    member.refresh_from_db()

    assert not member.permissions.exists()
    assert member.status == BusinessMember.Status.REMOVED


def test_concurrent_grant_and_revoke_are_serialized():
    business, owner_identity, owner = create_business_with_owner("grant-concurrent")
    _, member = create_member(business, "grant-concurrent-target")

    grant = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    revoke = authenticated_client(owner_identity).delete(
        permission_url(business, member, Permission.USE_POS),
    )
    re_grant = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )

    assert grant.status_code == 201
    assert revoke.status_code == 204
    assert re_grant.status_code == 201
    assert member.permissions.filter(permission=Permission.USE_POS).count() == 1


def test_permission_payloads_never_expose_internal_ids():
    business, owner_identity, owner = create_business_with_owner("grant-payload")
    _, member = create_member(business, "grant-payload-target")

    grant_response = authenticated_client(owner_identity).post(
        permissions_url(business, member),
        {"permission": Permission.USE_POS},
        format="json",
    )
    read_response = authenticated_client(owner_identity).get(
        permissions_url(business, member),
    )
    catalog_response = authenticated_client(owner_identity).get(
        catalog_url(business),
    )

    for response in (grant_response, read_response, catalog_response):
        assert response.status_code in (200, 201)
        payload = response.content.decode()
        assert str(member.identity_id) not in payload
        assert str(business.id) not in payload
        assert str(member.id) not in payload
