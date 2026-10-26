from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.catalog.models import Product, ProductCategory
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement
from apps.receivables.models import Receivable


pytestmark = pytest.mark.django_db
Permission = BusinessMemberPermission.Permission


def api_client(identity):
    client = APIClient()
    client.force_authenticate(user=identity)
    return client


def grant(member, *permissions):
    BusinessMemberPermission.objects.bulk_create(
        [BusinessMemberPermission(member=member, permission=permission) for permission in permissions]
    )


@pytest.fixture
def operations_context():
    category = ProductCategory.objects.create(
        code="OPERATION_PERMISSIONS",
        name="Operation permissions",
        slug="operation-permissions",
    )
    business = Business.objects.create(name="Separated operations")
    owner = CarriIdentity.objects.create(carri_subject="operation-owner")
    sales_user = CarriIdentity.objects.create(carri_subject="operation-sales-only")
    invoice_user = CarriIdentity.objects.create(carri_subject="operation-invoice-only")
    no_permission_user = CarriIdentity.objects.create(carri_subject="operation-no-permission")
    outsider = CarriIdentity.objects.create(carri_subject="operation-outsider")
    BusinessMember.objects.create(business=business, identity=owner, role=BusinessMember.Role.OWNER)
    sales_member = BusinessMember.objects.create(business=business, identity=sales_user, role=BusinessMember.Role.EMPLOYEE)
    invoice_member = BusinessMember.objects.create(business=business, identity=invoice_user, role=BusinessMember.Role.EMPLOYEE)
    BusinessMember.objects.create(business=business, identity=no_permission_user, role=BusinessMember.Role.EMPLOYEE)
    other_business = Business.objects.create(name="Foreign operations")
    BusinessMember.objects.create(business=other_business, identity=outsider, role=BusinessMember.Role.OWNER)
    grant(
        sales_member,
        Permission.SALE_VIEW,
        Permission.SALE_CREATE,
        Permission.SALE_UPDATE,
        Permission.SALE_LINE_VIEW,
        Permission.SALE_LINE_CREATE,
        Permission.SALE_COMPLETE,
        Permission.SALE_CANCEL,
    )
    grant(
        invoice_member,
        Permission.INVOICE_VIEW,
        Permission.INVOICE_CREATE,
        Permission.INVOICE_UPDATE,
        Permission.INVOICE_ISSUE,
        Permission.INVOICE_CANCEL,
        Permission.INVOICE_PAYMENT_CREATE,
    )
    product = Product.objects.create(
        business=business,
        category=category,
        name="Separated product",
        selling_price=Decimal("20.00"),
        cost_price=Decimal("10.00"),
        currency="CDF",
        attributes={},
    )
    inventory = InventoryItem.objects.create(business=business, product=product)
    apply_stock_movement(
        inventory_item=inventory,
        movement_type=StockMovement.Type.IN,
        performed_by=owner,
        quantity=Decimal("10.000"),
    )
    return {
        "business": business,
        "base": f"/api/v1/businesses/{business.public_id}/",
        "owner": owner,
        "sales_user": sales_user,
        "invoice_user": invoice_user,
        "no_permission_user": no_permission_user,
        "outsider": outsider,
        "product": product,
        "inventory": inventory,
    }


def create_draft(context, operation_type):
    client = api_client(context["owner"])
    payload = {"operation_type": operation_type}
    if operation_type == "INVOICE":
        payload["customer_name_snapshot"] = "Invoice customer"
    created = client.post(context["base"] + "sales/", payload, format="json")
    assert created.status_code == 201
    sale_id = created.data["public_id"]
    line = client.post(
        context["base"] + f"sales/{sale_id}/lines/",
        {"product": context["product"].public_id, "quantity": "1.000"},
        format="json",
    )
    assert line.status_code == 201
    return sale_id, line.data["public_id"]


def test_sale_and_invoice_permissions_are_mutually_exclusive(operations_context):
    context = operations_context
    direct_id, direct_line_id = create_draft(context, "DIRECT_SALE")
    invoice_id, invoice_line_id = create_draft(context, "INVOICE")
    sales_client = api_client(context["sales_user"])
    invoice_client = api_client(context["invoice_user"])
    no_permission_client = api_client(context["no_permission_user"])
    base = context["base"]

    sales_list = sales_client.get(base + "sales/")
    invoice_list = invoice_client.get(base + "sales/")
    assert sales_list.status_code == invoice_list.status_code == 200
    assert {item["operation_type"] for item in sales_list.data} == {"DIRECT_SALE"}
    assert {item["operation_type"] for item in invoice_list.data} == {"INVOICE"}
    assert no_permission_client.get(base + "sales/").status_code == 403
    assert sales_client.get(base + "customers/search/").status_code == 200
    assert invoice_client.get(base + "customers/search/").status_code == 200

    assert sales_client.post(base + "sales/", {"operation_type": "INVOICE", "customer_name_snapshot": "Blocked"}, format="json").status_code == 403
    assert invoice_client.post(base + "sales/", {"operation_type": "DIRECT_SALE"}, format="json").status_code == 403
    assert sales_client.get(base + f"sales/{invoice_id}/").status_code == 403
    assert invoice_client.get(base + f"sales/{direct_id}/").status_code == 403

    assert sales_client.patch(base + f"sales/{invoice_id}/", {"reference": "blocked"}, format="json").status_code == 403
    assert invoice_client.patch(base + f"sales/{direct_id}/", {"reference": "blocked"}, format="json").status_code == 403
    assert sales_client.post(base + f"sales/{invoice_id}/lines/", {"product": context["product"].public_id, "quantity": "1.000"}, format="json").status_code == 403
    assert invoice_client.post(base + f"sales/{direct_id}/lines/", {"product": context["product"].public_id, "quantity": "1.000"}, format="json").status_code == 403
    assert sales_client.delete(base + f"sales/{invoice_id}/lines/{invoice_line_id}/").status_code == 403
    assert invoice_client.delete(base + f"sales/{direct_id}/lines/{direct_line_id}/").status_code == 403
    assert sales_client.post(base + f"sales/{invoice_id}/complete/", {"amount_paid": "0.00"}, format="json").status_code == 403
    assert invoice_client.post(base + f"sales/{direct_id}/complete/", {"amount_paid": "20.00", "payment_method": "CASH"}, format="json").status_code == 403
    assert sales_client.post(base + f"sales/{invoice_id}/cancel/", {}, format="json").status_code == 403
    assert invoice_client.post(base + f"sales/{direct_id}/cancel/", {}, format="json").status_code == 403


def test_invoice_payments_are_idempotent_tenant_scoped_and_deduct_stock_once(operations_context):
    context = operations_context
    invoice_id, _ = create_draft(context, "INVOICE")
    owner_client = api_client(context["owner"])
    issued = owner_client.post(
        context["base"] + f"sales/{invoice_id}/complete/",
        {"amount_paid": "0.00"},
        format="json",
    )
    assert issued.status_code == 200
    receivable = Receivable.objects.get(sale__public_id=invoice_id)
    payments_url = context["base"] + f"receivables/{receivable.public_id}/payments/"
    context["inventory"].refresh_from_db()
    assert context["inventory"].quantity == Decimal("10.000")

    assert api_client(context["sales_user"]).get(payments_url).status_code == 403
    assert api_client(context["sales_user"]).post(payments_url, {"amount": "5.00", "payment_method": "CASH"}, format="json").status_code == 403
    assert api_client(context["no_permission_user"]).post(payments_url, {"amount": "5.00", "payment_method": "CASH"}, format="json").status_code == 403
    assert api_client(context["outsider"]).post(payments_url, {"amount": "5.00", "payment_method": "CASH"}, format="json").status_code == 404

    invoice_client = api_client(context["invoice_user"])
    headers = {"HTTP_IDEMPOTENCY_KEY": "invoice-payment-once"}
    first = invoice_client.post(payments_url, {"amount": "5.00", "payment_method": "CASH"}, format="json", **headers)
    retry = invoice_client.post(payments_url, {"amount": "5.00", "payment_method": "CASH"}, format="json", **headers)
    assert first.status_code == retry.status_code == 201
    assert first.data["public_id"] == retry.data["public_id"]
    context["inventory"].refresh_from_db()
    assert context["inventory"].quantity == Decimal("9.000")
    sale_movements = StockMovement.objects.filter(movement_type=StockMovement.Type.SALE)
    assert sale_movements.count() == 1

    second = invoice_client.post(payments_url, {"amount": "5.00", "payment_method": "CARD"}, format="json", HTTP_IDEMPOTENCY_KEY="invoice-payment-two")
    assert second.status_code == 201
    context["inventory"].refresh_from_db()
    assert context["inventory"].quantity == Decimal("9.000")
    assert sale_movements.count() == 1
    assert invoice_client.get(payments_url).status_code == 200
