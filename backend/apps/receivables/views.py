from rest_framework.views import APIView
from rest_framework.response import Response
from decimal import Decimal
from django.core.exceptions import ValidationError
from apps.businesses.permissions import can_manage_business, membership_for
from apps.businesses.models import Business
from .models import Receivable
from .serializers import R,P
from .services import add_payment
class V(APIView):
 def b(self,r,x):return Business.objects.filter(public_id=x,members__identity=r.user,members__status='ACTIVE').first()
 def nf(self):return Response({'detail':'Not found.'},404)
class List(V):
 def get(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  q=Receivable.objects.filter(business=b)
  if r.query_params.get('status'):q=q.filter(status=r.query_params['status'])
  if r.query_params.get('customer'):q=q.filter(customer__public_id=r.query_params['customer'])
  if r.query_params.get('overdue')=='true':q=[x for x in q if x.is_overdue]
  return Response(R(q,many=True).data)
class Detail(List):
 def o(self,b,x):return Receivable.objects.filter(business=b,public_id=x).first()
 def get(self,r,business_public_id,receivable_public_id):
  b=self.b(r,business_public_id);o=self.o(b,receivable_public_id) if b else None;return Response(R(o).data) if o else self.nf()
 def patch(self,r,business_public_id,receivable_public_id):
  b=self.b(r,business_public_id);o=self.o(b,receivable_public_id) if b else None
  if not o:return self.nf()
  if not can_manage_business(membership_for(r.user,b)): return Response({'detail':'Forbidden.'},403)
  for k in ('due_date','notes'):
   if k in r.data:setattr(o,k,r.data[k])
  o.save(update_fields=('due_date','notes','updated_at'));return Response(R(o).data)
class Payments(Detail):
 def get(self,r,business_public_id,receivable_public_id):
  b=self.b(r,business_public_id);o=self.o(b,receivable_public_id) if b else None;return Response(P(o.payments.all(),many=True).data) if o else self.nf()
 def post(self,r,business_public_id,receivable_public_id):
  b=self.b(r,business_public_id);o=self.o(b,receivable_public_id) if b else None
  if not o:return self.nf()
  try:p=add_payment(o,r.user,Decimal(str(r.data.get('amount'))),r.data.get('payment_method'),r.data.get('reference',''),r.data.get('notes',''))
  except (ValidationError,TypeError):return Response({'detail':'Invalid payment.'},400)
  return Response(P(p).data,201)
from drf_spectacular.utils import extend_schema
List.serializer_class=R;Detail.serializer_class=R;Payments.serializer_class=P
Detail.http_method_names=['get','patch','head','options'];Payments.http_method_names=['get','post','head','options']
List.get=extend_schema(tags=['Receivables'],operation_id='receivable_list',responses={200:R(many=True)})(List.get);Detail.get=extend_schema(tags=['Receivables'],operation_id='receivable_retrieve',responses={200:R})(Detail.get);Detail.patch=extend_schema(tags=['Receivables'],operation_id='receivable_update',request=R,responses={200:R})(Detail.patch);Payments.get=extend_schema(tags=['Receivables'],operation_id='receivable_payment_list',responses={200:P(many=True)})(Payments.get);Payments.post=extend_schema(tags=['Receivables'],operation_id='receivable_payment_create',request=P,responses={201:P})(Payments.post)
