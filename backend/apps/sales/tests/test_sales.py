import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember
from apps.catalog.models import ProductCategory,Product
from apps.inventory.models import InventoryItem,StockMovement
pytestmark=pytest.mark.django_db
def test_internal_sale():
 c=ProductCategory.objects.create(code='SALECAT',name='Sale',slug='salecat');b=Business.objects.create(name='B');u=CarriIdentity.objects.create(carri_subject='seller');BusinessMember.objects.create(business=b,identity=u,role='EMPLOYEE');p=Product.objects.create(business=b,category=c,name='P',selling_price='5',currency='CDF',attributes={});i=InventoryItem.objects.create(business=b,product=p);from apps.inventory.services import apply_stock_movement;apply_stock_movement(inventory_item=i,movement_type='IN',performed_by=u,quantity=10)
 a=APIClient();a.force_authenticate(user=u);base=f'/api/v1/businesses/{b.public_id}/';s=a.post(base+'sales/',{},format='json');assert s.status_code==201 and s.data['public_id'].startswith('SA');sa=s.data['public_id'];l=a.post(base+f'sales/{sa}/lines/',{'product':p.public_id,'quantity':'2.000'},format='json');assert l.status_code==201 and l.data['unit_price']=='5.00';r=a.post(base+f'sales/{sa}/complete/',{},format='json');assert r.status_code==200 and r.data['status']=='COMPLETED';assert InventoryItem.objects.get(pk=i.pk).quantity==8;assert StockMovement.objects.filter(movement_type='SALE').exists()


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
