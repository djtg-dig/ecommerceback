from datetime import date
from decimal import Decimal
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.businesses.models import Business
from apps.businesses.permissions import can_manage_business,membership_for
from .models import ExpenseCategory,Expense
class V(APIView):
 def b(self,r,x):return Business.objects.filter(public_id=x,members__identity=r.user,members__status='ACTIVE').first()
 def nf(self):return Response({'detail':'Not found.'},404)
class Categories(V):
 def get(self,r,business_public_id):
  b=self.b(r,business_public_id);return Response([{'public_id':x.public_id,'code':x.code,'name':x.name,'is_system':x.is_system,'is_active':x.is_active} for x in ExpenseCategory.objects.filter(business=b)]) if b else self.nf()
 def post(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  if not can_manage_business(membership_for(r.user,b)):return Response({'detail':'Forbidden'},403)
  code=r.data.get('code') or r.data.get('name','').upper().replace(' ','_');x=ExpenseCategory.objects.create(business=b,code=code,name=r.data.get('name'),description=r.data.get('description',''));return Response({'public_id':x.public_id,'code':x.code,'name':x.name},201)
class Expenses(V):
 def get(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  q=Expense.objects.filter(business=b)
  for field,param in [('status','status'),('currency','currency'),('payment_method','payment_method')]:
   if r.query_params.get(param):q=q.filter(**{field:r.query_params[param]})
  if r.query_params.get('category'):q=q.filter(category__public_id=r.query_params['category'])
  if r.query_params.get('date_from'):q=q.filter(expense_date__gte=r.query_params['date_from'])
  if r.query_params.get('date_to'):q=q.filter(expense_date__lte=r.query_params['date_to'])
  return Response([{'public_id':x.public_id,'category':x.category.public_id,'amount':str(x.amount),'currency':x.currency,'status':x.status,'expense_date':x.expense_date} for x in q])
 def post(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  if not can_manage_business(membership_for(r.user,b)):return Response({'detail':'Forbidden'},403)
  c=ExpenseCategory.objects.filter(business=b,public_id=r.data.get('category'),is_active=True).first()
  try:amount=Decimal(str(r.data.get('amount')))
  except:amount=0
  if not c or amount<=0:return Response({'detail':'Invalid expense'},400)
  x=Expense.objects.create(business=b,category=c,amount=amount,currency=r.data.get('currency',b.primary_currency),payment_method=r.data.get('payment_method','CASH'),expense_date=r.data.get('expense_date',date.today()),description=r.data.get('description',''),reference=r.data.get('reference',''),created_by=r.user);return Response({'public_id':x.public_id},201)
