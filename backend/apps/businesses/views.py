from rest_framework import permissions,status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Business,BusinessCategory
from .permissions import can_manage_business,can_view_members,membership_for
from .serializers import BusinessCreateSerializer,BusinessMemberSerializer,BusinessSerializer,BusinessUpdateSerializer,CategorySerializer
from .services import create_business,replace_categories
def accessible(i):return Business.objects.filter(members__identity=i,members__status="ACTIVE").distinct()
class BusinessesView(APIView):
 def get(self,r):return Response(BusinessSerializer(accessible(r.user),many=True).data)
 def post(self,r):
  s=BusinessCreateSerializer(data=r.data);s.is_valid(raise_exception=True)
  try:b=create_business(r.user,dict(s.validated_data))
  except ValueError as e:return Response({"detail":str(e)},400)
  return Response(BusinessSerializer(b).data,201)
class BusinessDetailView(APIView):
 def get_object(self,r,p):return accessible(r.user).filter(public_id=p).first()
 def get(self,r,p):
  b=self.get_object(r,p);return Response(BusinessSerializer(b).data) if b else Response({"detail":"Not found."},404)
 def patch(self,r,p):
  b=self.get_object(r,p)
  if not b:return Response({"detail":"Not found."},404)
  if not can_manage_business(membership_for(r.user,b)):return Response({"detail":"Forbidden."},403)
  s=BusinessUpdateSerializer(b,data=r.data,partial=True);s.is_valid(raise_exception=True);data=dict(s.validated_data);cats=data.pop("categories",None);primary=data.pop("primary_category",None);s=BusinessUpdateSerializer(b,data=data,partial=True);s.is_valid(raise_exception=True);s.save()
  if cats is not None:
   try:replace_categories(b,cats,primary)
   except ValueError as e:return Response({"detail":str(e)},400)
  return Response(BusinessSerializer(b).data)
class BusinessMembersView(APIView):
 def get(self,r,p):
  b=accessible(r.user).filter(public_id=p).first()
  if not b:return Response({"detail":"Not found."},404)
  if not can_view_members(membership_for(r.user,b)):return Response({"detail":"Forbidden."},403)
  return Response(BusinessMemberSerializer(b.members.all(),many=True).data)
class BusinessCategoriesView(APIView):
 authentication_classes=[];permission_classes=[permissions.AllowAny]
 def get(self,r):return Response(CategorySerializer(BusinessCategory.objects.filter(is_active=True),many=True).data)
