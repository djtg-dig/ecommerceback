from rest_framework import serializers
from .models import Business, BusinessMember
class BusinessCreateSerializer(serializers.ModelSerializer):
 class Meta: model=Business; fields=("name","description","address","zone","primary_currency","phone")
class BusinessSerializer(serializers.ModelSerializer):
 class Meta: model=Business; fields=("id","name","description","address","zone","primary_currency","phone","status","created_at","updated_at")
class BusinessUpdateSerializer(serializers.ModelSerializer):
 class Meta: model=Business; fields=("name","description","address","zone","primary_currency","phone")
class BusinessMemberSerializer(serializers.ModelSerializer):
 identity_id=serializers.UUIDField(source="identity_id",read_only=True)
 class Meta: model=BusinessMember; fields=("id","identity_id","role","status","joined_at")
