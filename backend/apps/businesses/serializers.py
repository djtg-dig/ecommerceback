from rest_framework import serializers
from .models import Business,BusinessCategory,BusinessMember
class CategorySerializer(serializers.ModelSerializer):
 class Meta:model=BusinessCategory;fields=("code","name","slug","description")
class BaseBusinessSerializer(serializers.ModelSerializer):
 categories=serializers.ListField(child=serializers.CharField(),write_only=True,required=False);primary_category=serializers.CharField(write_only=True,required=False)
class BusinessCreateSerializer(BaseBusinessSerializer):
 class Meta:model=Business;fields=("name","description","address","zone","primary_currency","phone","categories","primary_category")
class BusinessUpdateSerializer(BaseBusinessSerializer):
 class Meta:model=Business;fields=("name","description","address","zone","primary_currency","phone","categories","primary_category")
class BusinessSerializer(serializers.ModelSerializer):
 categories=serializers.SerializerMethodField();primary_category=serializers.SerializerMethodField()
 class Meta:model=Business;fields=("public_id","name","description","address","zone","primary_currency","phone","status","categories","primary_category","created_at","updated_at")
 def get_categories(self,o):return CategorySerializer([x.category for x in o.category_memberships.select_related("category").all()],many=True).data
 def get_primary_category(self,o):
  x=o.category_memberships.select_related("category").filter(is_primary=True).first();return CategorySerializer(x.category).data if x else None
class BusinessMemberSerializer(serializers.ModelSerializer):
 identity_id=serializers.UUIDField(source="identity_id",read_only=True)
 class Meta:model=BusinessMember;fields=("id","identity_id","role","status","joined_at")
