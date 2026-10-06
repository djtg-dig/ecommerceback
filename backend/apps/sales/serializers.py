from decimal import Decimal
from rest_framework import serializers
from apps.catalog.models import Product,ProductVariant
from .models import Customer,Sale,SaleLine
class CustomerSerializer(serializers.ModelSerializer):
 class Meta:model=Customer;fields=('public_id','name','phone','email','address','notes','is_active');read_only_fields=('public_id',)
class SaleSerializer(serializers.ModelSerializer):
 customer=serializers.CharField(source='customer.public_id',read_only=True,allow_null=True);total=serializers.DecimalField(max_digits=16,decimal_places=2,read_only=True)
 class Meta:model=Sale;fields=('public_id','customer','status','currency','reference','notes','total','created_at','completed_at')
class SaleWrite(serializers.ModelSerializer):
 customer=serializers.SlugRelatedField(slug_field='public_id',queryset=Customer.objects.all(),allow_null=True,required=False);currency=serializers.ChoiceField(choices=('CDF','USD'),required=False)
 class Meta:model=Sale;fields=('customer','currency','reference','notes')
 def validate_customer(self,x):
  if x and x.business_id!=self.context['business'].id:raise serializers.ValidationError('External customer')
  return x
class LineSerializer(serializers.ModelSerializer):
 product=serializers.CharField(source='product.public_id',read_only=True,allow_null=True);variant=serializers.CharField(source='variant.public_id',read_only=True,allow_null=True)
 class Meta:model=SaleLine;fields=('public_id','product','variant','quantity','unit_price','unit_cost_snapshot','line_total')
class LineWrite(serializers.Serializer):
 product=serializers.SlugRelatedField(slug_field='public_id',queryset=Product.objects.all(),required=False);variant=serializers.SlugRelatedField(slug_field='public_id',queryset=ProductVariant.objects.all(),required=False);quantity=serializers.DecimalField(max_digits=14,decimal_places=3,min_value=Decimal('.001'));unit_price=serializers.DecimalField(max_digits=14,decimal_places=2,min_value=0,required=False)
 def validate(self,a):
  from .services import target
  target(self.context['sale'],a.get('product'),a.get('variant'))
  if 'unit_price' not in a:a['unit_price']=a['variant'].effective_selling_price if a.get('variant') else a['product'].selling_price
  return a
