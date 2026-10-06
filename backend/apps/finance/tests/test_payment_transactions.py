from datetime import timedelta
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessPaymentMethod
from apps.finance.models import FinancialMovement, PaymentTransaction
from apps.finance.services import create_financial_movement, reverse_movement
from apps.sales.models import Customer, Sale

pytestmark = pytest.mark.django_db


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def business_with_members():
    suffix = uuid.uuid4().hex
    business = Business.objects.create(name="Payment methods")
    owner = CarriIdentity.objects.create(carri_subject=f"payment-owner-{suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"payment-manager-{suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"payment-employee-{suffix}")
    for identity, role in ((owner, "OWNER"), (manager, "MANAGER"), (employee, "EMPLOYEE")):
        BusinessMember.objects.create(business=business, identity=identity, role=role)
    return business, owner, manager, employee


def sale_for(business, actor):
    customer = Customer.objects.create(business=business, name="Trace customer")
    return Sale.objects.create(business=business, customer=customer, currency="CDF", created_by=actor)


def create_sale_movement(business, actor, **kwargs):
    sale = sale_for(business, actor)
    return create_financial_movement(
        business=business,
        direction=FinancialMovement.Direction.INFLOW,
        amount=Decimal("10.00"),
        payment_method="CASH",
        event_type=FinancialMovement.EventType.SALE_PAYMENT,
        created_by=actor,
        sale=sale,
        **kwargs,
    )


def test_business_creation_initializes_default_payment_methods():
    identity = CarriIdentity.objects.create(carri_subject="payment-create")
    response = client_for(identity).post(
        "/api/v1/businesses/",
        {"name": "Configured shop"},
        format="json",
    )
    business = Business.objects.get(public_id=response.data["public_id"])
    assert response.status_code == 201
    assert set(business.payment_methods.values_list("category", flat=True)) == {
        "CASH", "MOBILE_MONEY", "BANK_TRANSFER", "CARD", "OTHER"
    }


def test_payment_method_api_permissions_tenant_isolation_and_employee_visibility():
    business, owner, manager, employee = business_with_members()
    other, outsider, _, _ = business_with_members()
    base = f"/api/v1/businesses/{business.public_id}/payment-methods/"
    created = client_for(owner).post(base, {"name": "M-Pesa", "category": "MOBILE_MONEY"}, format="json")
    assert created.status_code == 201
    assert created.data["public_id"].startswith("PM")
    assert client_for(manager).post(base, {"name": "Orange", "category": "MOBILE_MONEY"}, format="json").status_code == 201
    assert client_for(employee).post(base, {"name": "Forbidden", "category": "CASH"}, format="json").status_code == 403
    detail = base + created.data["public_id"] + "/"
    assert client_for(owner).patch(detail, {"name": "M-Pesa Boutique", "is_active": False}, format="json").status_code == 200
    visible = client_for(employee).get(base)
    assert visible.status_code == 200
    assert all(row["is_active"] for row in visible.data)
    assert client_for(outsider).get(base.replace(business.public_id, other.public_id)).status_code == 200
    assert client_for(outsider).get(base).status_code == 404


def test_payment_transaction_snapshots_dates_actor_and_legacy_compatibility():
    business, owner, _, _ = business_with_members()
    movement = create_sale_movement(business, owner, transaction_reference="", occurred_at=timezone.now() - timedelta(days=1))
    trace = movement.payment_transaction
    method = trace.business_payment_method
    assert trace.recording_mode == PaymentTransaction.RecordingMode.MANUAL
    assert trace.transaction_reference == ""
    assert trace.category_snapshot == "CASH"
    assert trace.method_name_snapshot == method.name
    assert trace.recorded_by_id == owner.id
    assert trace.occurred_at < timezone.now()
    method.name = "Caisse renommée"
    method.save()
    trace.refresh_from_db()
    assert trace.method_name_snapshot == "Argent liquide"
    assert FinancialMovement.objects.filter(payment_transaction=trace).count() == 1


def test_payment_method_validation_rejects_inactive_other_tenant_and_future_date():
    business, owner, _, _ = business_with_members()
    other, _, _, _ = business_with_members()
    inactive = BusinessPaymentMethod.objects.create(business=business, name="Inactive", category="CASH", is_active=False)
    foreign = BusinessPaymentMethod.objects.create(business=other, name="Foreign", category="CASH")
    with pytest.raises(ValidationError):
        create_sale_movement(business, owner, business_payment_method=inactive)
    with pytest.raises(ValidationError):
        create_sale_movement(business, owner, business_payment_method=foreign)
    with pytest.raises(ValidationError):
        create_sale_movement(business, owner, occurred_at=timezone.now() + timedelta(minutes=1))


def test_payment_transaction_and_movement_roll_back_together_and_reversal_has_no_trace():
    business, owner, _, _ = business_with_members()
    original = create_sale_movement(business, owner)
    assert PaymentTransaction.objects.count() == 1
    with pytest.raises(ValidationError):
        reverse_movement(original, created_by=owner, reason="No sale reversal")
    # A historical movement is still valid without an informational trace.
    historical_sale = sale_for(business, owner)
    historical = FinancialMovement.objects.create(
        business=business,
        direction="INFLOW",
        amount=Decimal("5"),
        currency="CDF",
        payment_method="CASH",
        event_type="SALE_PAYMENT",
        occurred_at=timezone.now(),
        created_by=owner,
        sale=historical_sale,
    )
    assert historical.payment_transaction_id is None


def test_default_payment_method_backfill_is_idempotent_for_existing_businesses():
    from django.apps import apps as django_apps
    from importlib import import_module
    create_default_payment_methods = import_module("apps.businesses.migrations.0004_default_payment_methods").create_default_payment_methods

    business = Business.objects.create(name="Pre-existing business")
    create_default_payment_methods(django_apps, None)
    create_default_payment_methods(django_apps, None)

    assert business.payment_methods.count() == 5


def test_summary_groups_categories_modes_methods_and_legacy_movements():
    from apps.finance.services import financial_summary

    business, owner, _, _ = business_with_members()
    first = create_sale_movement(business, owner)
    historical_sale = sale_for(business, owner)
    FinancialMovement.objects.create(
        business=business, direction="INFLOW", amount=Decimal("20"), currency="CDF",
        payment_method="MOBILE_MONEY", event_type="SALE_PAYMENT",
        occurred_at=timezone.now(), created_by=owner, sale=historical_sale,
    )
    summary = financial_summary(FinancialMovement.objects.filter(business=business))
    categories = {row["category"]: row for row in summary["by_category"]}
    modes = {row["mode"]: row for row in summary["by_recording_mode"]}
    assert summary["total_inflow"] == Decimal("30")
    assert categories["CASH"]["inflow"] == Decimal("10")
    assert categories["MOBILE_MONEY"]["inflow"] == Decimal("20")
    assert modes["MANUAL"]["inflow"] == Decimal("10")
    assert modes["UNCLASSIFIED"]["inflow"] == Decimal("20")
    assert summary["by_business_payment_method"][0]["payment_method"] == first.payment_transaction.business_payment_method.public_id
