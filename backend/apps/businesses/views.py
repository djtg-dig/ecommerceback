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
 def get_object(self,r,public_id):return accessible(r.user).filter(public_id=public_id).first()
 def get(self,r,public_id):
  b=self.get_object(r,public_id);return Response(BusinessSerializer(b).data) if b else Response({"detail":"Not found."},404)
 def patch(self,r,public_id):
  b=self.get_object(r,public_id)
  if not b:return Response({"detail":"Not found."},404)
  if not can_manage_business(membership_for(r.user,b)):return Response({"detail":"Forbidden."},403)
  s=BusinessUpdateSerializer(b,data=r.data,partial=True);s.is_valid(raise_exception=True);data=dict(s.validated_data);cats=data.pop("categories",None);primary=data.pop("primary_category",None);s=BusinessUpdateSerializer(b,data=data,partial=True);s.is_valid(raise_exception=True);s.save()
  if cats is not None:
   try:replace_categories(b,cats,primary)
   except ValueError as e:return Response({"detail":str(e)},400)
  return Response(BusinessSerializer(b).data)
class BusinessMembersView(APIView):
 def get(self,r,public_id):
  b=accessible(r.user).filter(public_id=public_id).first()
  if not b:return Response({"detail":"Not found."},404)
  if not can_view_members(membership_for(r.user,b)):return Response({"detail":"Forbidden."},403)
  return Response(BusinessMemberSerializer(b.members.all(),many=True).data)
class BusinessCategoriesView(APIView):
 authentication_classes=[];permission_classes=[permissions.AllowAny]
 def get(self,r):return Response(CategorySerializer(BusinessCategory.objects.filter(is_active=True),many=True).data)

# APIViews use explicit schemas because their serializer direction depends on the method.
from drf_spectacular.utils import OpenApiParameter, extend_schema
from .serializers import BusinessCreateSerializer, BusinessMemberSerializer, BusinessSerializer, BusinessUpdateSerializer, CategorySerializer

_business_id = OpenApiParameter("public_id", str, OpenApiParameter.PATH, description="Identifiant public Business, format SH + 10 caractères.")
BusinessesView.get = extend_schema(tags=["Businesses"], operation_id="business_list", responses={200: BusinessSerializer(many=True)})(BusinessesView.get)
BusinessesView.post = extend_schema(tags=["Businesses"], operation_id="business_create", request=BusinessCreateSerializer, responses={201: BusinessSerializer, 400: None})(BusinessesView.post)
BusinessDetailView.get = extend_schema(tags=["Businesses"], operation_id="business_retrieve", parameters=[_business_id], responses={200: BusinessSerializer, 404: None})(BusinessDetailView.get)
BusinessDetailView.patch = extend_schema(tags=["Businesses"], operation_id="business_update", parameters=[_business_id], request=BusinessUpdateSerializer, responses={200: BusinessSerializer, 403: None, 404: None})(BusinessDetailView.patch)
BusinessMembersView.get = extend_schema(tags=["Businesses"], operation_id="business_member_list", parameters=[_business_id], responses={200: BusinessMemberSerializer(many=True), 403: None, 404: None})(BusinessMembersView.get)
BusinessCategoriesView.get = extend_schema(tags=["Business Categories"], operation_id="business_category_list", auth=[], responses={200: CategorySerializer(many=True)})(BusinessCategoriesView.get)
