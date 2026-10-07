import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember
from apps.catalog.models import ProductCategory,Product
from apps.inventory.models import InventoryItem,StockMovement
from apps.sales.models import Customer, Sale
pytestmark=pytest.mark.django_db
def test_internal_sale():
 c=ProductCategory.objects.create(code='SALECAT',name='Sale',slug='salecat');b=Business.objects.create(name='B');u=CarriIdentity.objects.create(carri_subject='seller');BusinessMember.objects.create(business=b,identity=u,role='EMPLOYEE');p=Product.objects.create(business=b,category=c,name='P',selling_price='5',cost_price='3',currency='CDF',attributes={});i=InventoryItem.objects.create(business=b,product=p);from apps.inventory.services import apply_stock_movement;apply_stock_movement(inventory_item=i,movement_type='IN',performed_by=u,quantity=10)
 a=APIClient();a.force_authenticate(user=u);base=f'/api/v1/businesses/{b.public_id}/';s=a.post(base+'sales/',{},format='json');assert s.status_code==201 and s.data['public_id'].startswith('SA');sa=s.data['public_id'];l=a.post(base+f'sales/{sa}/lines/',{'product':p.public_id,'quantity':'2.000'},format='json');assert l.status_code==201 and l.data['unit_price']=='5.00';r=a.post(base+f'sales/{sa}/complete/',{'amount_paid':'10.00','payment_method':'CASH'},format='json');assert r.status_code==200 and r.data['status']=='COMPLETED';assert InventoryItem.objects.get(pk=i.pk).quantity==8;assert StockMovement.objects.filter(movement_type='SALE').exists(); movement = FinancialMovement.objects.get(sale__public_id=sa); assert movement.payment_transaction_id and movement.payment_transaction.recording_mode == 'MANUAL'


def test_sale_currency_is_imposed_by_business():
    category = ProductCategory.objects.create(code="SALECUR", name="Currency", slug="sale-cur")
    business = Business.objects.create(name="Currency business", primary_currency="CDF")
    identity = CarriIdentity.objects.create(carri_subject="sale-currency")
    BusinessMember.objects.create(business=business, identity=identity, role="EMPLOYEE")

    client = APIClient()
    client.force_authenticate(user=identity)
    url = f"/api/v1/businesses/{business.public_id}/sales/"

    assert client.post(url, {}, format="json").data["currency"] == "CDF"
    assert client.post(url, {"currency": "USD"}, format="json").status_code == 400

from decimal import Decimal
from unittest.mock import patch

from apps.finance.models import FinancialMovement, PaymentTransaction
from apps.receivables.models import Receivable, ReceivablePayment


def build_sale_context(customer=True):
    category, _ = ProductCategory.objects.get_or_create(code="SALELOT3", defaults={"name": "Sales", "slug": "sales-lot3"})
    business = Business.objects.create(name="Sales lot 3")
    employee, _ = CarriIdentity.objects.get_or_create(carri_subject="sales-lot3-employee")
    BusinessMember.objects.create(business=business, identity=employee, role="EMPLOYEE")
    product = Product.objects.create(
        business=business, category=category, name="Item", selling_price="100.00", cost_price="60.00", currency="CDF", attributes={}
    )
    inventory = InventoryItem.objects.create(business=business, product=product)
    from apps.inventory.services import apply_stock_movement
    apply_stock_movement(inventory_item=inventory, movement_type="IN", performed_by=employee, quantity=10)
    customer_object = Customer.objects.create(business=business, name="Known") if customer else None
    client = APIClient()
    client.force_authenticate(user=employee)
    base = f"/api/v1/businesses/{business.public_id}/"
    sale_response = client.post(base + "sales/", {"customer": customer_object.public_id} if customer else {}, format="json")
    sale_id = sale_response.data["public_id"]
    assert client.post(base + f"sales/{sale_id}/lines/", {"product": product.public_id, "quantity": "1"}, format="json").status_code == 201
    return business, employee, product, inventory, customer_object, client, base, sale_id


def test_complete_requires_explicit_accurate_payment_method_and_creates_sale_inflow():
    business, employee, _, _, _, client, base, sale_id = build_sale_context()
    endpoint = base + f"sales/{sale_id}/complete/"
    assert client.post(endpoint, {}, format="json").status_code == 400
    assert client.post(endpoint, {"amount_paid": "100"}, format="json").status_code == 400
    assert client.post(endpoint, {"amount_paid": "0", "payment_method": "CASH"}, format="json").status_code == 400
    assert client.post(endpoint, {"amount_paid": "100", "payment_method": "CASHHH"}, format="json").status_code == 400
    response = client.post(endpoint, {"amount_paid": "100", "payment_method": "MOBILE_MONEY"}, format="json")
    assert response.status_code == 200
    movement = FinancialMovement.objects.get(sale__public_id=sale_id)
    assert movement.event_type == FinancialMovement.EventType.SALE_PAYMENT
    assert movement.amount == Decimal("100.00")
    assert movement.payment_method == "MOBILE_MONEY"
    assert movement.created_by_id == employee.id
    assert movement.currency == business.primary_currency
    assert not Receivable.objects.filter(sale__public_id=sale_id).exists()
    assert client.post(endpoint, {"amount_paid": "100", "payment_method": "CASH"}, format="json").status_code == 400


def test_partial_credit_and_anonymous_sale_rules_prevent_double_counting():
    _, employee, _, inventory, _, client, base, sale_id = build_sale_context()
    response = client.post(base + f"sales/{sale_id}/complete/", {"amount_paid": "40", "payment_method": "CASH"}, format="json")
    assert response.status_code == 200
    receivable = Receivable.objects.get(sale__public_id=sale_id)
    payment = receivable.payments.get()
    movement = FinancialMovement.objects.get(receivable_payment=payment)
    assert receivable.balance == Decimal("60.00")
    assert movement.amount == Decimal("40.00")
    assert not FinancialMovement.objects.filter(sale__public_id=sale_id).exists()
    assert InventoryItem.objects.get(pk=inventory.pk).quantity == 9

    _, _, _, anonymous_inventory, _, anonymous_client, anonymous_base, anonymous_sale_id = build_sale_context(customer=False)
    assert anonymous_client.post(anonymous_base + f"sales/{anonymous_sale_id}/complete/", {"amount_paid": "100", "payment_method": "CASH"}, format="json").status_code == 200
    _, _, _, credit_inventory, _, credit_client, credit_base, credit_sale_id = build_sale_context(customer=False)
    assert credit_client.post(credit_base + f"sales/{credit_sale_id}/complete/", {"amount_paid": "0"}, format="json").status_code == 400
    assert InventoryItem.objects.get(pk=credit_inventory.pk).quantity == 10


def test_credit_sale_creates_no_financial_movement_and_finance_failure_rolls_back():
    _, _, _, _, _, client, base, sale_id = build_sale_context()
    assert client.post(base + f"sales/{sale_id}/complete/", {"amount_paid": "0"}, format="json").status_code == 200
    assert Receivable.objects.get(sale__public_id=sale_id).balance == Decimal("100.00")
    assert not FinancialMovement.objects.filter().exists()

    _, _, _, inventory, _, client, base, sale_id = build_sale_context()
    with patch("apps.sales.services.create_financial_movement", side_effect=RuntimeError("finance unavailable")):
        with pytest.raises(RuntimeError):
            from apps.sales.services import complete
            complete(Sale.objects.get(public_id=sale_id), client.handler._force_user, Decimal("100"), "CASH")
    assert Sale.objects.get(public_id=sale_id).status == "DRAFT"
    assert InventoryItem.objects.get(pk=inventory.pk).quantity == 10
    assert not StockMovement.objects.filter(movement_type="SALE", reference_id__isnull=False).filter(reference_id__contains=sale_id).exists()

    _, employee, _, inventory, _, client, base, sale_id = build_sale_context()
    with patch("apps.receivables.services.create_financial_movement", side_effect=RuntimeError("finance unavailable")):
        with pytest.raises(RuntimeError):
            from apps.sales.services import complete
            complete(Sale.objects.get(public_id=sale_id), employee, Decimal("40"), "CASH")
    assert Sale.objects.get(public_id=sale_id).status == "DRAFT"
    assert InventoryItem.objects.get(pk=inventory.pk).quantity == 10
    assert not Receivable.objects.filter(sale__public_id=sale_id).exists()
    assert not ReceivablePayment.objects.exists()
