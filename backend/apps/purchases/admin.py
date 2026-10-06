from django.contrib import admin
from .models import Supplier,Purchase,PurchaseLine,SupplierPayment
@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
 list_display=('public_id','name','business','is_active');readonly_fields=('id','public_id','created_at','updated_at')
@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
 list_display=('public_id','business','supplier','status','currency','created_at');readonly_fields=('id','public_id','status','created_by','confirmed_by','received_by','cancelled_by','confirmed_at','received_at','cancelled_at','created_at','updated_at')
 def has_change_permission(self,request,obj=None): return obj is None or obj.status!='RECEIVED'
@admin.register(PurchaseLine)
class PurchaseLineAdmin(admin.ModelAdmin):
 list_display=('public_id','purchase','product','variant','quantity','unit_cost','line_total');readonly_fields=('id','public_id','line_total','created_at','updated_at')

@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
 list_display=('public_id','purchase','amount','payment_method','paid_at','created_by','reversed_at','created_at')
 list_filter=('payment_method','paid_at','reversed_at')
 search_fields=('public_id','purchase__public_id','purchase__supplier__name')
 readonly_fields=tuple(field.name for field in SupplierPayment._meta.fields)
 def has_add_permission(self,request):return False
 def has_delete_permission(self,request,obj=None):return False
