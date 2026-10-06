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
