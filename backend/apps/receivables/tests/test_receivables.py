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
 c=ProductCategory.objects.create(code='RCAT',name='R',slug='r-cat');b=Business.objects.create(name='B');o=CarriIdentity.objects.create(carri_subject='rc-owner');e=CarriIdentity.objects.create(carri_subject='rc-employee');BusinessMember.objects.create(business=b,identity=o,role='OWNER');BusinessMember.objects.create(business=b,identity=e,role='EMPLOYEE');p=Product.objects.create(business=b,category=c,name='P',selling_price='100',currency='CDF',attributes={});i=InventoryItem.objects.create(business=b,product=p);apply_stock_movement(inventory_item=i,movement_type='IN',performed_by=o,quantity=10);cu=Customer.objects.create(business=b,name='Client');return b,o,e,p,i,cu
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
 b,o,_,p,_,cu=data;a,base,sa=sale(b,o,p,cu);assert a.post(base+f'sales/{sa}/complete/',{},format='json').status_code==200 and not Receivable.objects.exists();_,_,sa=sale(b,o,p,cu);a.post(base+f'sales/{sa}/complete/',{'amount_paid':'0'},format='json');r=Receivable.objects.get(sale__public_id=sa);r.due_date=timezone.localdate()-timedelta(days=1);r.save();assert r.is_overdue;assert a.get(base+'receivables/?overdue=true').status_code==200
