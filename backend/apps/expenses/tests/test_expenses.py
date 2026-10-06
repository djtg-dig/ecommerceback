import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CarriIdentity
from apps.businesses.models import Business,BusinessMember
from apps.expenses.models import ExpenseCategory
from apps.expenses.services import ensure_default_expense_categories
pytestmark=pytest.mark.django_db
def test_expenses_categories_and_creation():
 b=Business.objects.create(name='B');u=CarriIdentity.objects.create(carri_subject='expense-owner');BusinessMember.objects.create(business=b,identity=u,role='OWNER');ensure_default_expense_categories(b);c=ExpenseCategory.objects.get(business=b,code='RENT');assert c.public_id.startswith('EC');a=APIClient();a.force_authenticate(user=u);base=f'/api/v1/businesses/{b.public_id}/';r=a.post(base+'expenses/',{'category':c.public_id,'amount':'10.00','description':'Loyer','payment_method':'CASH'},format='json');assert r.status_code==201 and r.data['public_id'].startswith('EX')
