import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember

def auth(identity):
 c=APIClient(); c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(identity).access_token}"); return c
@pytest.mark.django_db
def test_create_business_creates_owner_and_is_scoped():
 identity=CarriIdentity.objects.create(carri_subject="owner")
 response=auth(identity).post("/api/v1/businesses/",{"name":"Shop","primary_currency":"CDF"},format="json")
 assert response.status_code==201
 business=Business.objects.get(); assert BusinessMember.objects.get(business=business,identity=identity).role=="OWNER"
 assert auth(CarriIdentity.objects.create(carri_subject="other")).get(f"/api/v1/businesses/{business.id}/").status_code==404
@pytest.mark.django_db
def test_roles_control_updates_and_member_list():
 owner=CarriIdentity.objects.create(carri_subject="owner2"); employee=CarriIdentity.objects.create(carri_subject="employee")
 business=Business.objects.create(name="Shop")
 BusinessMember.objects.create(business=business,identity=owner,role="OWNER")
 BusinessMember.objects.create(business=business,identity=employee,role="EMPLOYEE")
 assert auth(owner).patch(f"/api/v1/businesses/{business.id}/",{"name":"New"},format="json").status_code==200
 assert auth(employee).patch(f"/api/v1/businesses/{business.id}/",{"name":"No"},format="json").status_code==403
 assert auth(employee).get(f"/api/v1/businesses/{business.id}/members/").status_code==403
