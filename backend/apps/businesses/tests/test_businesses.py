from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.businesses.permissions import can_manage_business, has_permission
from apps.businesses.services import grant_permission, revoke_permission


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
    assert membership.is_owner is True
    assert membership.title == "Gérant"
    assert membership.status == "ACTIVE"

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
        is_owner=True,
        title="Gérant",
    )
    BusinessMember.objects.create(
        business=business,
        identity=employee,
        role="EMPLOYEE",
        is_owner=False,
        title="Employé",
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


@pytest.mark.django_db
def test_primary_currency_is_immutable_after_business_creation():
    identity = CarriIdentity.objects.create(carri_subject="currency-owner")
    create_response = auth(identity).post(
        "/api/v1/businesses/",
        {"name": "USD shop", "primary_currency": "USD"},
        format="json",
    )
    business_id = create_response.data["public_id"]

    update_response = auth(identity).patch(
        f"/api/v1/businesses/{business_id}/",
        {"primary_currency": "CDF"},
        format="json",
    )

    assert create_response.status_code == 201
    assert update_response.status_code == 400
    assert Business.objects.get(public_id=business_id).primary_currency == "USD"


@pytest.mark.django_db
def test_owner_has_all_permissions_by_design():
    business = Business.objects.create(name="Perm shop")
    owner = CarriIdentity.objects.create(carri_subject="perm-owner")
    member = BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
        is_owner=True,
        title="Gérant",
    )
    assert has_permission(member, BusinessMemberPermission.Permission.VIEW_MEMBERS)
    assert has_permission(member, BusinessMemberPermission.Permission.MANAGE_INVENTORY)
    assert has_permission(member, BusinessMemberPermission.Permission.CREATE_EXPENSES)


@pytest.mark.django_db
def test_non_owner_without_permission_cannot_manage():
    business = Business.objects.create(name="No perm shop")
    owner = CarriIdentity.objects.create(carri_subject="perm-owner2")
    employee = CarriIdentity.objects.create(carri_subject="no-perm-emp")
    BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
        is_owner=True,
        title="Gérant",
    )
    emp_member = BusinessMember.objects.create(
        business=business,
        identity=employee,
        role="EMPLOYEE",
        is_owner=False,
        title="Employé",
    )
    assert not has_permission(emp_member, BusinessMemberPermission.Permission.UPDATE_BUSINESS)
    assert not has_permission(emp_member, BusinessMemberPermission.Permission.MANAGE_MEMBERS)
    assert auth(employee).patch(
        f"/api/v1/businesses/{business.public_id}/",
        {"name": "No"},
        format="json",
    ).status_code == 403


@pytest.mark.django_db
def test_professional_title_never_grants_permissions():
    business = Business.objects.create(name="Title shop")
    identity = CarriIdentity.objects.create(carri_subject="titled-manager")
    member = BusinessMember.objects.create(
        business=business,
        identity=identity,
        role=BusinessMember.Role.MANAGER,
        title="Gérant",
    )

    assert not member.is_owner
    assert not can_manage_business(member)
    assert not has_permission(
        member,
        BusinessMemberPermission.Permission.UPDATE_BUSINESS,
    )
    assert not member.permissions.exists()


@pytest.mark.django_db
def test_suspension_blocks_permissions():
    business = Business.objects.create(name="Susp shop")
    owner = CarriIdentity.objects.create(carri_subject="susp-owner")
    member = CarriIdentity.objects.create(carri_subject="susp-member")
    owner_membership = BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
        is_owner=True,
        title="Gérant",
    )
    emp = BusinessMember.objects.create(
        business=business,
        identity=member,
        role="EMPLOYEE",
        is_owner=False,
        title="Employé",
    )
    BusinessMemberPermission.objects.create(
        member=emp, permission=BusinessMemberPermission.Permission.CREATE_EXPENSES
    )
    assert has_permission(emp, BusinessMemberPermission.Permission.CREATE_EXPENSES)
    emp.status = BusinessMember.Status.SUSPENDED
    emp.save()
    emp.refresh_from_db()
    assert not has_permission(emp, BusinessMemberPermission.Permission.CREATE_EXPENSES)
    assert auth(member).get(
        f"/api/v1/businesses/{business.public_id}/"
    ).status_code == 404
    assert has_permission(owner_membership, BusinessMemberPermission.Permission.UPDATE_BUSINESS)


@pytest.mark.django_db
def test_last_owner_protection():
    business = Business.objects.create(name="Last owner shop")
    owner = CarriIdentity.objects.create(carri_subject="last-owner")
    member = BusinessMember.objects.create(
        business=business,
        identity=owner,
        role="OWNER",
        is_owner=True,
        title="Gérant",
    )
    member.is_owner = False
    with pytest.raises(Exception):
        member.save()
    member.refresh_from_db()
    assert member.is_owner is True

    member.status = BusinessMember.Status.SUSPENDED
    with pytest.raises(ValidationError):
        member.save()
    member.refresh_from_db()
    assert member.status == BusinessMember.Status.ACTIVE

    with pytest.raises(ValidationError):
        member.delete()
    assert BusinessMember.objects.filter(pk=member.pk).exists()

    second_identity = CarriIdentity.objects.create(carri_subject="second-owner")
    with pytest.raises(ValidationError):
        BusinessMember.objects.create(
            business=business,
            identity=second_identity,
            role=BusinessMember.Role.OWNER,
            is_owner=True,
            title="Gérant",
        )


@pytest.mark.django_db
def test_migration_preserves_old_roles_without_privilege_escalation():
    business = Business.objects.create(name="Mig shop")
    old_owner = CarriIdentity.objects.create(carri_subject="old-owner")
    old_manager = CarriIdentity.objects.create(carri_subject="old-manager")
    old_employee = CarriIdentity.objects.create(carri_subject="old-employee")
    BusinessMember.objects.create(business=business, identity=old_owner, role="OWNER")
    BusinessMember.objects.create(business=business, identity=old_manager, role="MANAGER")
    BusinessMember.objects.create(business=business, identity=old_employee, role="EMPLOYEE")
    migration = import_module(
        "apps.businesses.migrations.0006_backfill_member_title_owner"
    )
    migration.backfill_is_owner_and_title(django_apps, None)
    owner_m = BusinessMember.objects.get(identity=old_owner)
    manager_m = BusinessMember.objects.get(identity=old_manager)
    employee_m = BusinessMember.objects.get(identity=old_employee)
    assert owner_m.is_owner is True
    assert owner_m.title == "Gérant"
    assert manager_m.is_owner is False
    assert manager_m.title == "Gestionnaire"
    assert not has_permission(manager_m, BusinessMemberPermission.Permission.UPDATE_BUSINESS)
    assert not can_manage_business(manager_m)
    assert auth(old_manager).patch(
        f"/api/v1/businesses/{business.public_id}/",
        {"name": "Forbidden legacy manager update"},
        format="json",
    ).status_code == 403
    assert employee_m.is_owner is False
    assert employee_m.title == "Employé"


@pytest.mark.django_db
def test_only_owner_can_grant_and_revoke_individual_permissions():
    business = Business.objects.create(name="Permission service shop")
    owner_identity = CarriIdentity.objects.create(carri_subject="service-owner")
    member_identity = CarriIdentity.objects.create(carri_subject="service-member")
    outsider_identity = CarriIdentity.objects.create(carri_subject="service-outsider")
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
        title="Caissier",
    )
    other_business = Business.objects.create(name="Permission other shop")
    outsider = BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
        is_owner=True,
        title="Gérant",
    )
    permission = BusinessMemberPermission.Permission.USE_POS

    permission_row = grant_permission(owner, member, permission)
    assert permission_row.member == member
    assert has_permission(member, permission)

    revoke_permission(owner, member, permission)
    assert not has_permission(member, permission)

    with pytest.raises(ValidationError):
        grant_permission(outsider, member, permission)

    member.status = BusinessMember.Status.SUSPENDED
    member.save()
    with pytest.raises(ValidationError):
        grant_permission(owner, member, permission)


@pytest.mark.django_db
def test_business_isolation_remains_enforced():
    business_a = Business.objects.create(name="Tenant A")
    business_b = Business.objects.create(name="Tenant B")
    user_a = CarriIdentity.objects.create(carri_subject="tenant-a-user")
    user_b = CarriIdentity.objects.create(carri_subject="tenant-b-user")
    BusinessMember.objects.create(
        business=business_a, identity=user_a, role="OWNER", is_owner=True, title="Gérant"
    )
    BusinessMember.objects.create(
        business=business_b, identity=user_b, role="OWNER", is_owner=True, title="Gérant"
    )
    assert auth(user_a).get(
        f"/api/v1/businesses/{business_b.public_id}/"
    ).status_code == 404
    assert auth(user_b).get(
        f"/api/v1/businesses/{business_a.public_id}/"
    ).status_code == 404
    assert auth(user_a).get(
        f"/api/v1/businesses/{business_a.public_id}/members/"
    ).status_code == 200
    assert auth(user_b).get(
        f"/api/v1/businesses/{business_a.public_id}/members/"
    ).status_code == 404


@pytest.mark.django_db
def test_unique_membership_per_business():
    business = Business.objects.create(name="Unique shop")
    identity = CarriIdentity.objects.create(carri_subject="unique-member")
    BusinessMember.objects.create(
        business=business,
        identity=identity,
        role="OWNER",
        is_owner=True,
        title="Gérant",
    )
    with pytest.raises(Exception):
        BusinessMember.objects.create(
            business=business,
            identity=identity,
            role="EMPLOYEE",
            is_owner=False,
            title="Employé",
        )
