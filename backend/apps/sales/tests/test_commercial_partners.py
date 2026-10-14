from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember, BusinessMemberPermission
from apps.catalog.models import Product, ProductCategory
from apps.purchases.models import Purchase, PurchaseLine, Supplier
from apps.purchases.services import add_supplier_payment
from apps.receivables.models import Receivable
from apps.receivables.services import add_payment
from apps.sales.models import Customer, Sale, SaleLine


pytestmark = pytest.mark.django_db


def api(identity=None):
    client = APIClient()
    if identity:
        client.force_authenticate(user=identity)
    return client


@pytest.fixture
def commercial_context():
    business = Business.objects.create(name="Commercial directory")
    other = Business.objects.create(name="Other directory")
    owner = CarriIdentity.objects.create(carri_subject="commercial-owner")
    limited = CarriIdentity.objects.create(carri_subject="commercial-limited")
    BusinessMember.objects.create(business=business, identity=owner, role="OWNER")
    BusinessMember.objects.create(business=other, identity=owner, role="OWNER")
    member = BusinessMember.objects.create(business=business, identity=limited, role="EMPLOYEE")
    BusinessMemberPermission.objects.create(member=member, permission="CUSTOMER_VIEW")
    customer = Customer.objects.create(business=business, name="Ada Client", phone="099000")
    supplier = Supplier.objects.create(business=business, name="Kivu Fournitures", email="kivu@example.com")
    category = ProductCategory.objects.create(code="PARTNERS", name="Partners", slug="partners")
    product = Product.objects.create(business=business, category=category, name="Article", selling_price="100", cost_price="50", currency="CDF")
    sale = Sale.objects.create(business=business, customer=customer, status=Sale.Status.COMPLETED, currency="CDF", created_by=owner)
    SaleLine.objects.create(sale=sale, product=product, quantity=Decimal("1"), unit_price=Decimal("100"), unit_cost_snapshot=Decimal("50"))
    receivable = Receivable.objects.create(business=business, sale=sale, customer=customer, currency="CDF", original_amount="100")
    add_payment(receivable, owner, Decimal("40"), "CASH")
    purchase = Purchase.objects.create(business=business, supplier=supplier, status=Purchase.Status.CONFIRMED, currency="CDF", created_by=owner)
    PurchaseLine.objects.create(purchase=purchase, product=product, quantity=Decimal("1"), unit_cost=Decimal("50"))
    add_supplier_payment(purchase, owner, Decimal("20"), "CASH")
    return business, other, owner, limited, customer, supplier, sale, purchase


def test_customer_directory_search_pagination_update_and_history(commercial_context):
    business, _, owner, _, customer, _, sale, _ = commercial_context
    endpoint = f"/api/v1/businesses/{business.public_id}/customers/"
    listed = api(owner).get(endpoint, {"q": "099", "ordering": "-created_at", "page_size": 1})
    legacy_list = api(owner).get(endpoint)
    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert listed.data["results"][0]["created_at"]
    assert isinstance(legacy_list.data, list)
    updated = api(owner).patch(f"{endpoint}{customer.public_id}/", {"name": "Ada Corrigée"}, format="json")
    profile = api(owner).get(f"{endpoint}{customer.public_id}/profile/")
    assert updated.status_code == 200
    assert Sale.objects.get(pk=sale.pk).customer_id == customer.id
    assert profile.status_code == 200
    assert profile.data["sales"]["results"][0]["public_id"] == sale.public_id
    assert profile.data["sales"]["results"][0]["payment_status"] == "PARTIALLY_PAID"
    assert profile.data["financial_summary"]["total_completed_sales"] == Decimal("100.00")
    assert profile.data["financial_summary"]["net_collected"] == Decimal("40.00")
    assert profile.data["financial_summary"]["outstanding_receivables"] == Decimal("60.00")


def test_customer_permissions_and_tenant_isolation(commercial_context):
    business, other, owner, limited, customer, _, _, _ = commercial_context
    endpoint = f"/api/v1/businesses/{business.public_id}/customers/{customer.public_id}/"
    profile = api(limited).get(f"{endpoint}profile/")
    assert profile.status_code == 200
    assert profile.data["sales"] is None
    assert profile.data["financial_summary"] is None
    assert api(limited).patch(endpoint, {"name": "Forbidden"}, format="json").status_code == 403
    assert api(owner).get(f"/api/v1/businesses/{other.public_id}/customers/{customer.public_id}/").status_code == 404
    assert api().get(endpoint).status_code == 401


def test_supplier_directory_profile_and_financial_summary(commercial_context):
    business, _, owner, _, _, supplier, _, purchase = commercial_context
    endpoint = f"/api/v1/businesses/{business.public_id}/suppliers/"
    listed = api(owner).get(endpoint, {"q": "kivu", "ordering": "name"})
    legacy_list = api(owner).get(endpoint)
    profile = api(owner).get(f"{endpoint}{supplier.public_id}/profile/")
    assert listed.status_code == 200
    assert listed.data["count"] == 1
    assert isinstance(legacy_list.data, list)
    assert profile.status_code == 200
    assert profile.data["purchases"]["results"][0]["public_id"] == purchase.public_id
    assert profile.data["purchases"]["results"][0]["payment_status"] == "PARTIALLY_PAID"
    assert profile.data["financial_summary"]["total_recognized_purchases"] == Decimal("50.00")
    assert profile.data["financial_summary"]["paid_amount"] == Decimal("20.00")
    assert profile.data["financial_summary"]["outstanding_payables"] == Decimal("30.00")


def test_supplier_cross_tenant_reference_remains_rejected(commercial_context):
    business, other, owner, _, _, supplier, _, _ = commercial_context
    response = api(owner).post(
        f"/api/v1/businesses/{other.public_id}/purchases/",
        {"supplier": supplier.public_id},
        format="json",
    )
    assert response.status_code == 400
