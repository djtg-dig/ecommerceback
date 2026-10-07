"""Discoverable regression tests for sale credit and receivable payments."""
from datetime import timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember
from apps.catalog.models import ProductCategory,Product
from apps.inventory.models import InventoryItem,StockMovement
from apps.inventory.services import apply_stock_movement
from apps.sales.models import Customer,Sale
from apps.receivables.models import Receivable,ReceivablePayment
pytestmark=pytest.mark.django_db
@pytest.fixture
def data():
 c=ProductCategory.objects.create(code='RCAT',name='R',slug='r-cat');b=Business.objects.create(name='B');o=CarriIdentity.objects.create(carri_subject='rc-owner');e=CarriIdentity.objects.create(carri_subject='rc-employee');BusinessMember.objects.create(business=b,identity=o,role='OWNER');BusinessMember.objects.create(business=b,identity=e,role='EMPLOYEE');p=Product.objects.create(business=b,category=c,name='P',selling_price='100',cost_price='60',currency='CDF',attributes={});i=InventoryItem.objects.create(business=b,product=p);apply_stock_movement(inventory_item=i,movement_type='IN',performed_by=o,quantity=10);cu=Customer.objects.create(business=b,name='Client');return b,o,e,p,i,cu
def api(u):x=APIClient();x.force_authenticate(user=u);return x
def sale(b,u,p,customer=None):
 a=api(u);base=f'/api/v1/businesses/{b.public_id}/';r=a.post(base+'sales/',({'customer':customer.public_id} if customer else {}),format='json');assert r.status_code==201;sa=r.data['public_id'];assert a.post(base+f'sales/{sa}/lines/',{'product':p.public_id,'quantity':'1.000'},format='json').status_code==201;return a,base,sa
def test_discovery_credit_and_initial_partial_payment(data):
 b,o,_,p,i,cu=data;a,base,sa=sale(b,o,p,cu);r=a.post(base+f'sales/{sa}/complete/',{'amount_paid':'40.00','payment_method':'CASH'},format='json');assert r.status_code==200;rc=Receivable.objects.get(sale__public_id=sa);assert rc.public_id.startswith('RC') and rc.original_amount==100 and rc.paid_amount==40 and rc.balance==60 and rc.status=='PARTIALLY_PAID';pay=rc.payments.get();assert pay.public_id.startswith('RP') and pay.payment_method=='CASH';assert InventoryItem.objects.get(pk=i.pk).quantity==9
def test_anonymous_credit_and_overpayment_roll_back(data):
 b,o,_,p,i,_=data;a,base,sa=sale(b,o,p);assert a.post(base+f'sales/{sa}/complete/',{'amount_paid':'0.00'},format='json').status_code==400;assert Sale.objects.get(public_id=sa).status=='DRAFT' and InventoryItem.objects.get(pk=i.pk).quantity==10 and not Receivable.objects.exists();assert a.post(base+f'sales/{sa}/complete/',{'amount_paid':'120.00'},format='json').status_code==400
def test_payment_lifecycle_permissions_and_metadata_patch(data):
 b,o,e,p,_,cu=data;a,base,sa=sale(b,o,p,cu);a.post(base+f'sales/{sa}/complete/',{'amount_paid':'0.00'},format='json');r=Receivable.objects.get();url=base+f'receivables/{r.public_id}/';assert api(e).patch(url,{'notes':'no'},format='json').status_code==403;assert a.patch(url,{'notes':'ok','original_amount':'1','status':'PAID'},format='json').status_code==200;r.refresh_from_db();assert r.original_amount==100 and r.status=='OPEN' and r.notes=='ok';payments=url+'payments/';assert api(e).post(payments,{'amount':'60.00','payment_method':'MOBILE_MONEY'},format='json').status_code==201;assert api(o).post(payments,{'amount':'50.00','payment_method':'CARD'},format='json').status_code==400;assert api(o).post(payments,{'amount':'40.00','payment_method':'BANK_TRANSFER'},format='json').status_code==201;r.refresh_from_db();assert r.status=='PAID' and r.balance==0 and r.settled_at and not r.is_overdue;assert api(o).post(payments,{'amount':'1.00','payment_method':'OTHER'},format='json').status_code==400
def test_due_date_filters_and_complete_default(data):
 b,o,_,p,_,cu=data;a,base,sa=sale(b,o,p,cu);assert a.post(base+f'sales/{sa}/complete/',{'amount_paid':'100.00','payment_method':'CASH'},format='json').status_code==200 and not Receivable.objects.exists();_,_,sa=sale(b,o,p,cu);a.post(base+f'sales/{sa}/complete/',{'amount_paid':'0'},format='json');r=Receivable.objects.get(sale__public_id=sa);r.due_date=timezone.localdate()-timedelta(days=1);r.save();assert r.is_overdue;assert a.get(base+'receivables/?overdue=true').status_code==200

from unittest.mock import patch

from django.core.exceptions import ValidationError
from apps.finance.models import FinancialMovement, PaymentTransaction


def test_initial_and_multiple_receivable_payments_create_exact_financial_ledger(data):
    business, owner, _, product, inventory, customer = data
    client, base, sale_id = sale(business, owner, product, customer)
    assert client.post(
        base + f"sales/{sale_id}/complete/",
        {"amount_paid": "20.00", "payment_method": "CASH"},
        format="json",
    ).status_code == 200
    receivable = Receivable.objects.get(sale__public_id=sale_id)
    payments_url = base + f"receivables/{receivable.public_id}/payments/"
    assert client.post(payments_url, {"amount": "30.00", "payment_method": "MOBILE_MONEY"}, format="json").status_code == 201
    assert client.post(payments_url, {"amount": "50.00", "payment_method": "BANK_TRANSFER"}, format="json").status_code == 201
    receivable.refresh_from_db()
    movements = FinancialMovement.objects.filter(receivable_payment__receivable=receivable)
    assert receivable.status == Receivable.Status.PAID
    assert receivable.paid_amount == Decimal("100.00")
    assert receivable.balance == Decimal("0.00")
    assert receivable.payments.count() == 3
    assert movements.count() == 3
    assert PaymentTransaction.objects.filter(financial_movement__in=movements).count() == 3
    assert sum(movement.amount for movement in movements) == Decimal("100.00")
    assert set(movements.values_list("payment_method", flat=True)) == {"CASH", "MOBILE_MONEY", "BANK_TRANSFER"}
    assert not FinancialMovement.objects.filter(sale__public_id=sale_id).exists()
    assert all(movement.created_by_id == owner.id for movement in movements)
    summary = api(owner).get(base + "financial-summary/")
    assert summary.status_code == 200
    assert summary.data["total_inflow"] == Decimal("100.00")
    assert InventoryItem.objects.get(pk=inventory.pk).quantity == 9


def test_receivable_payment_idempotency_conflict_immutability_and_finance_rollback(data):
    business, owner, _, product, _, customer = data
    client, base, sale_id = sale(business, owner, product, customer)
    assert client.post(base + f"sales/{sale_id}/complete/", {"amount_paid": "0"}, format="json").status_code == 200
    receivable = Receivable.objects.get(sale__public_id=sale_id)
    url = base + f"receivables/{receivable.public_id}/payments/"
    headers = {"HTTP_IDEMPOTENCY_KEY": "retry-payment-1"}
    first = client.post(url, {"amount": "40", "payment_method": "CASH"}, format="json", **headers)
    retry = client.post(url, {"amount": "40", "payment_method": "CASH"}, format="json", **headers)
    conflict = client.post(url, {"amount": "41", "payment_method": "CASH"}, format="json", **headers)
    assert first.status_code == retry.status_code == 201
    assert first.data["public_id"] == retry.data["public_id"]
    assert conflict.status_code == 409
    payment = ReceivablePayment.objects.get(public_id=first.data["public_id"])
    assert FinancialMovement.objects.filter(receivable_payment=payment).count() == 1
    with pytest.raises(ValidationError):
        payment.delete()
    payment.reference = "changed"
    with pytest.raises(ValidationError):
        payment.save()

    before_payments = receivable.payments.count()
    with patch("apps.receivables.services.create_financial_movement", side_effect=RuntimeError("finance unavailable")):
        with pytest.raises(RuntimeError):
            from apps.receivables.services import add_payment
            add_payment(receivable, owner, Decimal("10"), "CARD")
    receivable.refresh_from_db()
    assert receivable.payments.count() == before_payments
    assert receivable.balance == Decimal("60.00")


def test_financial_summary_counts_only_real_collections(data):
    business, owner, _, product, _, customer = data
    product.selling_price = Decimal("100000.00")
    product.save(update_fields=("selling_price", "updated_at"))
    client = api(owner)
    base = f"/api/v1/businesses/{business.public_id}/"

    def create_sale(quantity):
        created = client.post(base + "sales/", {"customer": customer.public_id}, format="json")
        sale_id = created.data["public_id"]
        assert client.post(
            base + f"sales/{sale_id}/lines/",
            {"product": product.public_id, "quantity": quantity},
            format="json",
        ).status_code == 201
        return sale_id

    paid_sale = create_sale("0.350")
    assert client.post(
        base + f"sales/{paid_sale}/complete/",
        {"amount_paid": "35000.00", "payment_method": "CASH"},
        format="json",
    ).status_code == 200
    credit_sale = create_sale("0.200")
    assert client.post(
        base + f"sales/{credit_sale}/complete/",
        {"amount_paid": "0"},
        format="json",
    ).status_code == 200
    receivable = Receivable.objects.get(sale__public_id=credit_sale)
    assert client.post(
        base + f"receivables/{receivable.public_id}/payments/",
        {"amount": "5000.00", "payment_method": "MOBILE_MONEY"},
        format="json",
    ).status_code == 201
    summary = client.get(base + "financial-summary/")
    assert summary.data["total_inflow"] == Decimal("40000.00")
    assert receivable.balance == Decimal("15000.00")
