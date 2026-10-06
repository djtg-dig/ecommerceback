from datetime import timedelta
from decimal import Decimal
import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business, BusinessMember

pytestmark = pytest.mark.django_db

def test_dashboard_permissions_and_period_validation():
    business=Business.objects.create(name='Dashboard')
    owner=CarriIdentity.objects.create(carri_subject='dash-owner')
    manager=CarriIdentity.objects.create(carri_subject='dash-manager')
    employee=CarriIdentity.objects.create(carri_subject='dash-employee')
    outsider=CarriIdentity.objects.create(carri_subject='dash-outsider')
    for identity,role in ((owner,'OWNER'),(manager,'MANAGER'),(employee,'EMPLOYEE')): BusinessMember.objects.create(business=business,identity=identity,role=role)
    url=f'/api/v1/businesses/{business.public_id}/dashboard/'
    def api(user):
        c=APIClient();c.force_authenticate(user=user);return c
    for user in (owner,manager):
        response=api(user).get(url);assert response.status_code==200;assert set(response.data)=={'generated_at','currency','period','sales','cash','receivables','inventory','purchases'}
    assert api(employee).get(url).status_code==404
    assert api(outsider).get(url).status_code==404
    assert api(owner).get(url,{'period':'last_7_days'}).status_code==200
    assert api(owner).get(url,{'period':'last_30_days'}).status_code==200
    assert api(owner).get(url,{'date_from':'2026-01-01','date_to':'2026-01-02'}).status_code==200
    assert api(owner).get(url,{'date_from':'2026-01-01'}).status_code==400
    assert api(owner).get(url,{'period':'no'}).status_code==400

def test_dashboard_empty_business_has_zero_compact_aggregates():
    business = Business.objects.create(name='Empty dashboard')
    owner = CarriIdentity.objects.create(carri_subject='dash-empty-owner')
    BusinessMember.objects.create(business=business, identity=owner, role='OWNER')
    client = APIClient(); client.force_authenticate(user=owner)
    response = client.get(f'/api/v1/businesses/{business.public_id}/dashboard/')
    assert response.status_code == 200
    assert response.data['currency'] == 'CDF'
    assert response.data['sales'] == {'total': Decimal('0'), 'count': 0}
    assert response.data['cash'] == {'inflow': Decimal('0'), 'outflow': Decimal('0'), 'net': Decimal('0')}
    assert response.data['inventory'] == {'out_of_stock_count': 0}
