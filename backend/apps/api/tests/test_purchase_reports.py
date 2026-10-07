from decimal import Decimal
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember
from apps.catalog.models import Product, ProductCategory
from apps.purchases.models import Purchase, PurchaseLine, Supplier, SupplierPayment
from apps.purchases.services import receive_purchase, transition

pytestmark = pytest.mark.django_db

def setup(suffix):
    business=Business.objects.create(name=suffix); owner=CarriIdentity.objects.create(carri_subject=f"purchase-report-{suffix}"); employee=CarriIdentity.objects.create(carri_subject=f"purchase-employee-{suffix}"); BusinessMember.objects.create(business=business,identity=owner,role="OWNER");BusinessMember.objects.create(business=business,identity=employee,role="EMPLOYEE")
    category,_=ProductCategory.objects.get_or_create(code="PURCHASE_REPORT",defaults={"name":"Purchase report","slug":"purchase-report"}); product=Product.objects.create(business=business,category=category,name=f"Product {suffix}",selling_price=Decimal("1"),cost_price=Decimal("1"),currency="CDF",attributes={})
    return business,owner,employee,product
def purchase(business,owner,product,status="RECEIVED",supplier=None,amounts=(Decimal("40000"),Decimal("60000"))):
    value=Purchase.objects.create(business=business,supplier=supplier,currency="CDF",created_by=owner)
    for amount in amounts: PurchaseLine.objects.create(purchase=value,product=product,quantity=Decimal("1"),unit_cost=amount)
    transition(value,"confirm",owner)
    if status=="RECEIVED": receive_purchase(value,owner)
    return value
def client(user):
    c=APIClient();c.force_authenticate(user=user);return c
def test_purchase_reports_received_and_debts():
    business,owner,employee,product=setup("main"); supplier=Supplier.objects.create(business=business,name="Supplier")
    received=purchase(business,owner,product,supplier=supplier); SupplierPayment.objects.create(purchase=received,amount=Decimal("20000"),payment_method="CASH",created_by=owner); SupplierPayment.objects.create(purchase=received,amount=Decimal("30000"),payment_method="CASH",created_by=owner)
    confirmed=purchase(business,owner,product,status="CONFIRMED",amounts=(Decimal("20000"),))
    c=client(owner); base=f"/api/v1/businesses/{business.public_id}/reports/"
    sales=c.get(base+"purchases/",{"group_by":"day"}).data; assert sales["total_purchases"]==Decimal("100000") and sales["purchases_count"]==1
    assert c.get(base+"purchases/",{"group_by":"week"}).status_code==200 and c.get(base+"purchases/",{"group_by":"month"}).status_code==200
    debts=c.get(base+"supplier-debts/").data; assert debts["total_outstanding"]==Decimal("70000") and debts["open_purchases_count"]==2
    assert c.get(base+"purchases/",{"group_by":"bad"}).status_code==400
    assert client(employee).get(base+"purchases/").status_code==404
def test_purchase_report_measurement(capsys):
    business,owner,_,product=setup("measure"); c=client(owner); base=f"/api/v1/businesses/{business.public_id}/reports/"
    with CaptureQueriesContext(connection) as ps:c.get(base+"purchases/")
    with CaptureQueriesContext(connection) as ds:c.get(base+"supplier-debts/")
    for _ in range(4):purchase(business,owner,product)
    with CaptureQueriesContext(connection) as pl:pr=c.get(base+"purchases/")
    with CaptureQueriesContext(connection) as dl:dr=c.get(base+"supplier-debts/")
    print(f"LOT3_MEASURE purchases={len(ps)}/{len(pl)} debts={len(ds)}/{len(dl)} payload={len(pr.content)}/{len(dr.content)}")
    assert len(ps)==len(pl) and len(dl)-len(ds)<=1
