from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from apps.businesses.models import Business
from .models import Customer,Sale,SaleLine
from .serializers import *
from .services import complete,cancel
class M:
 def b(self,r,x):return Business.objects.filter(public_id=x,members__identity=r.user,members__status='ACTIVE').first()
 def nf(self):return Response({'detail':'Not found.'},404)
class Customers(M,APIView):
 def get(self,r,business_public_id):
  b=self.b(r,business_public_id);return Response(CustomerSerializer(Customer.objects.filter(business=b),many=True).data) if b else self.nf()
 def post(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  s=CustomerSerializer(data=r.data);s.is_valid(raise_exception=True);return Response(CustomerSerializer(s.save(business=b)).data,201)
class Sales(M,APIView):
 def get(self,r,business_public_id):
  b=self.b(r,business_public_id);return Response(SaleSerializer(Sale.objects.filter(business=b),many=True).data) if b else self.nf()
 def post(self,r,business_public_id):
  b=self.b(r,business_public_id)
  if not b:return self.nf()
  s=SaleWrite(data=r.data,context={'business':b});s.is_valid(raise_exception=True);o=s.save(business=b,created_by=r.user,currency=s.validated_data.get('currency',b.primary_currency));return Response(SaleSerializer(o).data,201)
class SD(Sales):
 def o(self,b,x):return Sale.objects.filter(business=b,public_id=x).first()
 def get(self,r,business_public_id,sale_public_id):
  b=self.b(r,business_public_id);o=self.o(b,sale_public_id) if b else None;return Response(SaleSerializer(o).data) if o else self.nf()
 def patch(self,r,business_public_id,sale_public_id):
  b=self.b(r,business_public_id);o=self.o(b,sale_public_id) if b else None
  if not o:return self.nf()
  if o.status!='DRAFT':return Response({'detail':'immutable'},400)
  s=SaleWrite(o,data=r.data,partial=True,context={'business':b});s.is_valid(raise_exception=True);s.save();return Response(SaleSerializer(o).data)
class Lines(SD):
 def get(self,r,business_public_id,sale_public_id):
  b=self.b(r,business_public_id);s=self.o(b,sale_public_id) if b else None;return Response(LineSerializer(s.lines.all(),many=True).data) if s else self.nf()
 def post(self,r,business_public_id,sale_public_id):
  b=self.b(r,business_public_id);s=self.o(b,sale_public_id) if b else None
  if not s:return self.nf()
  if s.status!='DRAFT':return Response({'detail':'immutable'},400)
  x=LineWrite(data=r.data,context={'sale':s});x.is_valid(raise_exception=True);o=SaleLine.objects.create(sale=s,**x.validated_data);return Response(LineSerializer(o).data,201)
class Action(SD):
 fn=None
 def post(self,r,business_public_id,sale_public_id):
  b=self.b(r,business_public_id);s=self.o(b,sale_public_id) if b else None
  if not s:return self.nf()
  try:o=complete(s,r.user) if self.fn=='complete' else cancel(s,r.user)
  except ValidationError as e:return Response({'detail':str(e)},400)
  return Response(SaleSerializer(o).data)
class Complete(Action):fn='complete'
class Cancel(Action):fn='cancel'
# Schema introspection metadata for the real APIView operations.
Customers.serializer_class=CustomerSerializer;Sales.serializer_class=SaleSerializer;SD.serializer_class=SaleSerializer;Lines.serializer_class=LineSerializer;Complete.serializer_class=SaleSerializer;Cancel.serializer_class=SaleSerializer
SD.http_method_names=['get','patch','head','options'];Lines.http_method_names=['get','post','head','options'];Complete.http_method_names=['post','options'];Cancel.http_method_names=['post','options']
from drf_spectacular.utils import extend_schema
Sales.get=extend_schema(tags=['Sales'],operation_id='sale_list',responses={200:SaleSerializer(many=True)})(Sales.get);Sales.post=extend_schema(tags=['Sales'],operation_id='sale_create',request=SaleWrite,responses={201:SaleSerializer})(Sales.post);SD.get=extend_schema(tags=['Sales'],operation_id='sale_retrieve',responses={200:SaleSerializer})(SD.get);SD.patch=extend_schema(tags=['Sales'],operation_id='sale_update',request=SaleWrite,responses={200:SaleSerializer})(SD.patch);Lines.get=extend_schema(tags=['Sales'],operation_id='sale_line_list',responses={200:LineSerializer(many=True)})(Lines.get);Lines.post=extend_schema(tags=['Sales'],operation_id='sale_line_create',request=LineWrite,responses={201:LineSerializer})(Lines.post);Customers.get=extend_schema(tags=['Customers'],operation_id='customer_list',responses={200:CustomerSerializer(many=True)})(Customers.get);Customers.post=extend_schema(tags=['Customers'],operation_id='customer_create',request=CustomerSerializer,responses={201:CustomerSerializer})(Customers.post)
