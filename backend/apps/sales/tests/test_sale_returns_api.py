import uuid
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory
from apps.finance.models import FinancialMovement
from apps.inventory.models import InventoryItem, StockMovement
from apps.receivables.models import Receivable, ReceivableAdjustment
from apps.receivables.services import add_payment
from apps.sales.models import Customer, Sale, SaleLine, SaleReturn
from apps.sales.services import create_sale_return


pytestmark = pytest.mark.django_db


def client_for(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def api_context(quantity=Decimal("10.000")):
    suffix = uuid.uuid4().hex
    category, _ = ProductCategory.objects.get_or_create(
        code="RETAPI",
        defaults={"name": "Return API", "slug": "return-api"},
    )
    business = Business.objects.create(name=f"Return API {suffix}")
    owner = CarriIdentity.objects.create(carri_subject=f"return-owner-{suffix}")
    manager = CarriIdentity.objects.create(carri_subject=f"return-manager-{suffix}")
    employee = CarriIdentity.objects.create(carri_subject=f"return-employee-{suffix}")
    outsider = CarriIdentity.objects.create(carri_subject=f"return-outsider-{suffix}")
    for identity, role in (
        (owner, BusinessMember.Role.OWNER),
        (manager, BusinessMember.Role.MANAGER),
        (employee, BusinessMember.Role.EMPLOYEE),
    ):
        BusinessMember.objects.create(
            business=business,
            identity=identity,
            role=role,
        )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Returnable",
        selling_price=Decimal("10.00"),
        cost_price=Decimal("4.00"),
        currency="CDF",
        attributes={},
    )
    inventory = InventoryItem.objects.create(
        business=business,
        product=product,
        quantity=Decimal("5.000"),
    )
    sale = Sale.objects.create(
        business=business,
        currency="CDF",
        created_by=owner,
        completed_by=owner,
        status=Sale.Status.COMPLETED,
    )
    line = SaleLine.objects.create(
        sale=sale,
        product=product,
        quantity=quantity,
        unit_price=Decimal("10.00"),
        unit_cost_snapshot=Decimal("4.00"),
    )
    url = (
        f"/api/v1/businesses/{business.public_id}/"
        f"sales/{sale.public_id}/returns/"
    )
    return business, owner, manager, employee, outsider, sale, line, inventory, url


def payload(line, quantity="1.000", **overrides):
    data = {
        "reason": "Client return",
        "returned_at": timezone.now().isoformat(),
        "lines": [{"sale_line": line.public_id, "quantity": quantity}],
    }
    data.update(overrides)
    return data


def test_post_permissions_required_header_and_business_isolation():
    business, owner, manager, employee, outsider, sale, line, _, url = api_context()
    request_data = payload(line)

    assert client_for(employee).post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="employee",
    ).status_code == 403
    assert client_for(outsider).post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="outsider",
    ).status_code == 404
    assert client_for(owner).post(url, request_data, format="json").status_code == 400

    owner_response = client_for(owner).post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="owner-return",
    )
    manager_response = client_for(manager).post(
        url,
        payload(line),
        format="json",
        HTTP_IDEMPOTENCY_KEY="manager-return",
    )
    assert owner_response.status_code == 201, owner_response.data
    assert manager_response.status_code == 201

    other_business = Business.objects.create(name="Other tenant")
    BusinessMember.objects.create(
        business=other_business,
        identity=owner,
        role=BusinessMember.Role.OWNER,
    )
    wrong_url = (
        f"/api/v1/businesses/{other_business.public_id}/"
        f"sales/{sale.public_id}/returns/"
    )
    assert client_for(owner).get(wrong_url).status_code == 404
    assert client_for(owner).post(
        wrong_url,
        payload(line),
        format="json",
        HTTP_IDEMPOTENCY_KEY="wrong-business",
    ).status_code == 404


def test_api_retry_and_conflict_do_not_duplicate_effects():
    _, owner, _, _, _, _, line, inventory, url = api_context()
    client = client_for(owner)
    returned_at = timezone.now().isoformat()
    request_data = payload(line, quantity="2.000", returned_at=returned_at)

    first = client.post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-retry",
    )
    retry = client.post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-retry",
    )
    conflict = client.post(
        url,
        payload(line, quantity="3.000", returned_at=returned_at),
        format="json",
        HTTP_IDEMPOTENCY_KEY="mobile-retry",
    )

    inventory.refresh_from_db()
    assert first.status_code == retry.status_code == 201
    assert first.data["public_id"] == retry.data["public_id"]
    assert conflict.status_code == 409
    assert SaleReturn.objects.filter(idempotency_key="mobile-retry").count() == 1
    assert StockMovement.objects.filter(
        movement_type=StockMovement.Type.RETURN,
        reference_type="SALE_RETURN_LINE",
    ).count() == 1
    assert inventory.quantity == Decimal("7.000")


def test_refund_method_requirement_and_retry_cover_all_atomic_effects():
    business, owner, _, _, _, sale, line, inventory, url = api_context()
    customer = Customer.objects.create(business=business, name="Credit customer")
    sale.customer = customer
    sale.save(update_fields=("customer", "updated_at"))
    receivable = Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100.00"),
    )
    payment = add_payment(receivable, owner, Decimal("40.00"), "CASH")
    refund_method = payment.financialmovement.payment_transaction.business_payment_method
    request_data = payload(line, quantity="7.000")
    client = client_for(owner)

    missing = client.post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="missing-method",
    )
    assert missing.status_code == 400
    assert not SaleReturn.objects.filter(idempotency_key="missing-method").exists()

    request_data["refund_payment_method"] = refund_method.public_id
    first = client.post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="atomic-retry",
    )
    retry = client.post(
        url,
        request_data,
        format="json",
        HTTP_IDEMPOTENCY_KEY="atomic-retry",
    )

    inventory.refresh_from_db()
    receivable.refresh_from_db()
    sale_return = SaleReturn.objects.get(idempotency_key="atomic-retry")
    assert first.status_code == retry.status_code == 201
    assert first.data["public_id"] == retry.data["public_id"]
    assert first.data["receivable_credit_amount"] == "60.00"
    assert first.data["refund_amount"] == "10.00"
    assert ReceivableAdjustment.objects.filter(sale_return=sale_return).count() == 1
    assert FinancialMovement.objects.filter(sale_return=sale_return).count() == 1
    assert StockMovement.objects.filter(
        movement_type=StockMovement.Type.RETURN,
        reference_id=sale_return.lines.get().public_id,
    ).count() == 1
    assert inventory.quantity == Decimal("12.000")
    assert receivable.balance == Decimal("0.00")


def test_zero_refund_needs_no_method_and_business_errors_are_400():
    business, owner, _, _, _, sale, line, _, url = api_context()
    customer = Customer.objects.create(business=business, name="Unpaid customer")
    sale.customer = customer
    sale.save(update_fields=("customer", "updated_at"))
    Receivable.objects.create(
        business=business,
        sale=sale,
        customer=customer,
        currency="CDF",
        original_amount=Decimal("100.00"),
    )
    client = client_for(owner)

    accepted = client.post(
        url,
        payload(line, quantity="3.000"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="credit-only",
    )
    rejected = client.post(
        url,
        payload(line, quantity="8.000"),
        format="json",
        HTTP_IDEMPOTENCY_KEY="too-much",
    )

    assert accepted.status_code == 201
    assert accepted.data["receivable_credit_amount"] == "30.00"
    assert accepted.data["refund_amount"] == "0.00"
    assert accepted.data["refund_payment_method"] is None
    assert rejected.status_code == 400


def test_get_is_paginated_sale_scoped_compact_and_constant_query_count():
    business, owner, manager, employee, _, sale, line, _, url = api_context(
        quantity=Decimal("30.000")
    )
    other_sale = Sale.objects.create(
        business=business,
        currency="CDF",
        created_by=owner,
        completed_by=owner,
        status=Sale.Status.COMPLETED,
    )
    other_line = SaleLine.objects.create(
        sale=other_sale,
        product=line.product,
        quantity=Decimal("1.000"),
        unit_price=Decimal("10.00"),
        unit_cost_snapshot=Decimal("4.00"),
    )
    for index in range(2):
        create_sale_return(
            sale=sale,
            actor=owner,
            reason=f"small-{index}",
            returned_at=timezone.now(),
            lines=[{"sale_line_public_id": line.public_id, "quantity": "1"}],
            idempotency_key=f"small-{index}",
        )
    other_return = create_sale_return(
        sale=other_sale,
        actor=owner,
        reason="other sale",
        returned_at=timezone.now(),
        lines=[{"sale_line_public_id": other_line.public_id, "quantity": "1"}],
        idempotency_key="other-sale",
    )
    manager_client = client_for(manager)
    with CaptureQueriesContext(connection) as small_queries:
        small = manager_client.get(url, {"page_size": 50})

    for index in range(2, 10):
        create_sale_return(
            sale=sale,
            actor=owner,
            reason=f"large-{index}",
            returned_at=timezone.now(),
            lines=[{"sale_line_public_id": line.public_id, "quantity": "1"}],
            idempotency_key=f"large-{index}",
        )
    with CaptureQueriesContext(connection) as large_queries:
        large = manager_client.get(url, {"page_size": 50})
    page = manager_client.get(url, {"page_size": 2})

    assert small.status_code == large.status_code == page.status_code == 200
    assert small.data["count"] == 2
    assert large.data["count"] == page.data["count"] == 10
    assert len(page.data["results"]) == 2
    assert page.data["next"] is not None
    assert other_return.public_id not in {
        row["public_id"] for row in large.data["results"]
    }
    assert len(small_queries) == len(large_queries)
    assert client_for(employee).get(url).status_code == 403
    assert set(large.data["results"][0]) == {
        "public_id",
        "status",
        "reason",
        "returned_at",
        "return_total",
        "receivable_credit_amount",
        "refund_amount",
        "refund_payment_method",
        "lines",
    }
    assert set(large.data["results"][0]["lines"][0]) == {
        "public_id",
        "sale_line",
        "quantity",
        "unit_price_snapshot",
        "unit_cost_snapshot",
        "line_total",
    }
