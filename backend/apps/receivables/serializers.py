from rest_framework import serializers
from .models import Receivable,ReceivablePayment
class R(serializers.ModelSerializer):
 sale=serializers.CharField(source='sale.public_id',read_only=True);customer=serializers.CharField(source='customer.public_id',read_only=True);paid_amount=serializers.DecimalField(max_digits=16,decimal_places=2,read_only=True);balance=serializers.DecimalField(max_digits=16,decimal_places=2,read_only=True);is_overdue=serializers.BooleanField(read_only=True)
 class Meta:model=Receivable;fields=('public_id','sale','customer','currency','original_amount','paid_amount','balance','status','due_date','notes','is_overdue','settled_at')
class P(serializers.ModelSerializer):
 class Meta:model=ReceivablePayment;fields=('public_id','amount','payment_method','reference','notes','paid_at');read_only_fields=('public_id','paid_at')
