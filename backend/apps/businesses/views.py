from rest_framework import permissions,status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Business
from .permissions import can_manage_business,can_view_members,membership_for
from .serializers import BusinessCreateSerializer,BusinessMemberSerializer,BusinessSerializer,BusinessUpdateSerializer
from .services import create_business

def accessible(identity): return Business.objects.filter(members__identity=identity,members__status="ACTIVE").distinct()
class BusinessesView(APIView):
 def get(self,request): return Response(BusinessSerializer(accessible(request.user),many=True).data)
 def post(self,request):
  s=BusinessCreateSerializer(data=request.data);s.is_valid(raise_exception=True); business=create_business(request.user,s.validated_data);return Response(BusinessSerializer(business).data,status=status.HTTP_201_CREATED)
class BusinessDetailView(APIView):
 def _business(self,request,pk): return accessible(request.user).filter(pk=pk).first()
 def get(self,request,pk):
  b=self._business(request,pk)
  return Response(BusinessSerializer(b).data) if b else Response({"detail":"Not found."},status=404)
 def patch(self,request,pk):
  b=self._business(request,pk)
  if not b:return Response({"detail":"Not found."},status=404)
  if not can_manage_business(membership_for(request.user,b)):return Response({"detail":"Forbidden."},status=403)
  s=BusinessUpdateSerializer(b,data=request.data,partial=True);s.is_valid(raise_exception=True);s.save();return Response(BusinessSerializer(b).data)
class BusinessMembersView(APIView):
 def get(self,request,pk):
  b=accessible(request.user).filter(pk=pk).first()
  if not b:return Response({"detail":"Not found."},status=404)
  if not can_view_members(membership_for(request.user,b)):return Response({"detail":"Forbidden."},status=403)
  return Response(BusinessMemberSerializer(b.members.select_related("identity").all(),many=True).data)
