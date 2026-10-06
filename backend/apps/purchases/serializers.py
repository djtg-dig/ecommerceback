from decimal import Decimal
from rest_framework import serializers
from apps.catalog.models import Product,ProductVariant
from .models import Supplier,Purchase,PurchaseLine
class SupplierSerializer(serializers.ModelSerializer):
 class Meta:model=Supplier;fields=('public_id','name','phone','email','address','notes','is_active','created_at','updated_at');read_only_fields=('public_id','created_at','updated_at')
class PurchaseLineSerializer(serializers.ModelSerializer):
 product=serializers.CharField(source='product.public_id',read_only=True,allow_null=True);variant=serializers.CharField(source='variant.public_id',read_only=True,allow_null=True)
 class Meta:model=PurchaseLine;fields=('public_id','product','variant','quantity','unit_cost','line_total','created_at','updated_at')
class PurchaseSerializer(serializers.ModelSerializer):
 supplier=serializers.CharField(source='supplier.public_id',read_only=True,allow_null=True);subtotal=serializers.DecimalField(max_digits=16,decimal_places=2,read_only=True);total=serializers.DecimalField(max_digits=16,decimal_places=2,read_only=True)
 class Meta:model=Purchase;fields=('public_id','supplier','status','currency','reference','notes','subtotal','total','created_at','confirmed_at','received_at','cancelled_at','updated_at')
class PurchaseWriteSerializer(serializers.ModelSerializer):
 supplier=serializers.SlugRelatedField(slug_field='public_id',queryset=Supplier.objects.all(),required=False,allow_null=True);currency=serializers.ChoiceField(choices=('CDF','USD'),required=False)
 class Meta:model=Purchase;fields=('supplier','currency','reference','notes')
 def validate_currency(self,value):
  business=self.context['business']
  if value!=business.primary_currency:raise serializers.ValidationError('Currency must match the Business primary currency.')
  return value
 def validate_supplier(self,x):
  if x and x.business_id!=self.context['business'].id:raise serializers.ValidationError('Supplier externe.')
  return x
class PurchaseLineWriteSerializer(serializers.Serializer):
 product=serializers.SlugRelatedField(slug_field='public_id',queryset=Product.objects.all(),required=False);variant=serializers.SlugRelatedField(slug_field='public_id',queryset=ProductVariant.objects.select_related('product').all(),required=False);quantity=serializers.DecimalField(max_digits=14,decimal_places=3,min_value=Decimal('0.001'));unit_cost=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0)
 def validate(self,a):
  from .services import validate_line_target
  try:validate_line_target(self.context['purchase'],a.get('product'),a.get('variant'))
  except Exception as e:raise serializers.ValidationError(str(e))
  return a
