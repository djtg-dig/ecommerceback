import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember
from apps.catalog.models import ProductCategory,Product
from apps.inventory.models import InventoryItem,StockMovement
from apps.purchases.models import Purchase
pytestmark=pytest.mark.django_db
@pytest.fixture
def ctx():
 c=ProductCategory.objects.create(code='BUY',name='Buy',slug='buy');b=Business.objects.create(name='B');o=CarriIdentity.objects.create(carri_subject='buyer');e=CarriIdentity.objects.create(carri_subject='empbuyer');BusinessMember.objects.create(business=b,identity=o,role='OWNER');BusinessMember.objects.create(business=b,identity=e,role='EMPLOYEE');p=Product.objects.create(business=b,category=c,name='P',selling_price='1',currency='CDF',attributes={});return b,o,e,p
def api(u):c=APIClient();c.force_authenticate(user=u);return c
def test_purchase_receive(ctx):
 b,o,e,p=ctx;base=f'/api/v1/businesses/{b.public_id}/';s=api(o).post(base+'suppliers/',{'name':'S'},format='json');assert s.status_code==201 and s.data['public_id'].startswith('SP')
 q=api(o).post(base+'purchases/',{'supplier':s.data['public_id']},format='json');assert q.status_code==201 and q.data['public_id'].startswith('PU') and q.data['currency']=='CDF';pu=q.data['public_id']
 line=api(o).post(base+f'purchases/{pu}/lines/',{'product':p.public_id,'quantity':'2.000','unit_cost':'3.50'},format='json');assert line.status_code==201 and line.data['line_total']=='7.00' and line.data['public_id'].startswith('PL')
 assert api(e).post(base+f'purchases/{pu}/confirm/',{},format='json').status_code==403
 assert api(o).post(base+f'purchases/{pu}/confirm/',{},format='json').status_code==200
 assert not InventoryItem.objects.exists()
 r=api(o).post(base+f'purchases/{pu}/receive/',{},format='json');assert r.status_code==200 and r.data['status']=='RECEIVED'
 item=InventoryItem.objects.get(product=p);assert item.quantity==2 and StockMovement.objects.get(inventory_item=item).reference_type=='PURCHASE'
 assert api(o).post(base+f'purchases/{pu}/receive/',{},format='json').status_code==400 and InventoryItem.objects.get(pk=item.pk).quantity==2
 assert api(o).patch(base+f'purchases/{pu}/',{'notes':'x'},format='json').status_code==400


def test_purchase_currency_is_imposed_by_business(ctx):
    business, owner, _, _ = ctx
    url = f"/api/v1/businesses/{business.public_id}/purchases/"

    assert api(owner).post(url, {}, format="json").data["currency"] == "CDF"
    assert api(owner).post(url, {"currency": "USD"}, format="json").status_code == 400

from decimal import Decimal
from django.core.exceptions import ValidationError
from apps.purchases.models import SupplierPayment
from apps.purchases.services import add_supplier_payment, reverse_supplier_payment
from apps.finance.models import FinancialMovement

def test_supplier_payment_confirmed_received_reversal_and_stock_separation(ctx):
 b,o,e,p=ctx;base=f'/api/v1/businesses/{b.public_id}/';supplier=api(o).post(base+'suppliers/',{'name':'Payment supplier'},format='json').data['public_id'];purchase_id=api(o).post(base+'purchases/',{'supplier':supplier},format='json').data['public_id'];purchase=Purchase.objects.get(public_id=purchase_id)
 with pytest.raises(ValidationError):add_supplier_payment(purchase,o,Decimal('10'),'CASH')
 api(o).post(base+f'purchases/{purchase_id}/lines/',{'product':p.public_id,'quantity':'2','unit_cost':'250'},format='json');api(o).post(base+f'purchases/{purchase_id}/confirm/',{},format='json');purchase.refresh_from_db();first=add_supplier_payment(purchase,o,Decimal('200'),'MOBILE_MONEY');purchase.refresh_from_db();assert purchase.paid_amount==200 and purchase.balance==300 and purchase.payment_status=='PARTIALLY_PAID';assert FinancialMovement.objects.get(supplier_payment=first).direction=='OUTFLOW'
 api(o).post(base+f'purchases/{purchase_id}/receive/',{},format='json');stock=InventoryItem.objects.get(product=p).quantity;purchase.refresh_from_db();second=add_supplier_payment(purchase,o,Decimal('300'),'BANK_TRANSFER');purchase.refresh_from_db();assert purchase.payment_status=='PAID' and purchase.balance==0
 reverse_supplier_payment(second,o,'Correction');purchase.refresh_from_db();assert purchase.paid_amount==200 and purchase.balance==300 and InventoryItem.objects.get(product=p).quantity==stock
 with pytest.raises(ValidationError):reverse_supplier_payment(second,o,'Again')
