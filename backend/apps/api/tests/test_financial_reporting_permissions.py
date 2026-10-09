import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import (
    Business,
    BusinessMember,
    BusinessMemberPermission,
)
from apps.businesses.services import grant_permission


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


@pytest.fixture
def reporting_permission_context():
    business = Business.objects.create(name="Financial reporting permissions")
    other_business = Business.objects.create(name="Other reporting tenant")
    owner_identity = CarriIdentity.objects.create(carri_subject="reporting-owner")
    manager_identity = CarriIdentity.objects.create(carri_subject="reporting-manager")
    suspended_identity = CarriIdentity.objects.create(
        carri_subject="reporting-suspended"
    )
    outsider_identity = CarriIdentity.objects.create(carri_subject="reporting-outsider")
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
    suspended = BusinessMember.objects.create(
        business=business,
        identity=suspended_identity,
        role=BusinessMember.Role.EMPLOYEE,
        title="Comptable",
    )
    BusinessMember.objects.create(
        business=other_business,
        identity=outsider_identity,
        role=BusinessMember.Role.OWNER,
    )
    base = f"/api/v1/businesses/{business.public_id}/"
    endpoints = {
        Permission.VIEW_FINANCIAL_SUMMARY: base + "financial-movements/",
        Permission.VIEW_DASHBOARD: base + "dashboard/",
        Permission.VIEW_PROFITABILITY: base + "profitability-summary/",
        Permission.VIEW_REPORTS: base + "reports/sales/",
    }

    return {
        "business": business,
        "owner": owner,
        "manager": manager,
        "suspended": suspended,
        "owner_identity": owner_identity,
        "manager_identity": manager_identity,
        "suspended_identity": suspended_identity,
        "outsider_identity": outsider_identity,
        "endpoints": endpoints,
    }


def test_owner_has_all_financial_reporting_permissions(reporting_permission_context):
    context = reporting_permission_context
    owner_client = client_for(context["owner_identity"])

    for endpoint in context["endpoints"].values():
        assert owner_client.get(endpoint).status_code == 200


def test_legacy_manager_needs_each_explicit_reporting_permission(
    reporting_permission_context,
):
    context = reporting_permission_context
    manager_client = client_for(context["manager_identity"])

    for permission, endpoint in context["endpoints"].items():
        assert manager_client.get(endpoint).status_code == 403
        grant_permission(context["owner"], context["manager"], permission)
        assert manager_client.get(endpoint).status_code == 200


def test_suspended_member_is_forbidden_and_foreign_member_is_hidden(
    reporting_permission_context,
):
    context = reporting_permission_context
    for permission in context["endpoints"]:
        grant_permission(context["owner"], context["suspended"], permission)
    context["suspended"].status = BusinessMember.Status.SUSPENDED
    context["suspended"].save(update_fields=("status", "updated_at"))

    suspended_client = client_for(context["suspended_identity"])
    outsider_client = client_for(context["outsider_identity"])
    for endpoint in context["endpoints"].values():
        assert suspended_client.get(endpoint).status_code == 403
        assert outsider_client.get(endpoint).status_code == 404


@pytest.mark.parametrize(
    "business_status",
    [Business.Status.SUSPENDED, Business.Status.ARCHIVED],
)
def test_inactive_business_keeps_authorized_reporting_reads(
    reporting_permission_context,
    business_status,
):
    context = reporting_permission_context
    context["business"].status = business_status
    context["business"].save(update_fields=("status", "updated_at"))
    owner_client = client_for(context["owner_identity"])

    for endpoint in context["endpoints"].values():
        assert owner_client.get(endpoint).status_code == 200
