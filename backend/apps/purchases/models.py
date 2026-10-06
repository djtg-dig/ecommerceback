"""Suppliers and procurement documents; stock is mutated only by receipt service."""
import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

class Supplier(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True); business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT,related_name='suppliers'); name=models.CharField(max_length=200); phone=models.CharField(max_length=40,blank=True); email=models.EmailField(blank=True); address=models.TextField(blank=True); notes=models.TextField(blank=True); is_active=models.BooleanField(default=True); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_supplier_public_id
  if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists(): raise ValidationError('Supplier public_id is immutable.')
  if not self.public_id:self.public_id=generate_supplier_public_id()
  return super().save(*a,**kw)

class Purchase(models.Model):
 class Status(models.TextChoices): DRAFT='DRAFT','Draft'; CONFIRMED='CONFIRMED','Confirmed'; RECEIVED='RECEIVED','Received'; CANCELLED='CANCELLED','Cancelled'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True); business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT,related_name='purchases'); supplier=models.ForeignKey(Supplier,null=True,blank=True,on_delete=models.PROTECT,related_name='purchases'); status=models.CharField(max_length=12,choices=Status.choices,default=Status.DRAFT); currency=models.CharField(max_length=3,choices=(('CDF','CDF'),('USD','USD'))); reference=models.CharField(max_length=120,blank=True); notes=models.TextField(blank=True); created_by=models.ForeignKey('accounts.CarriIdentity',on_delete=models.PROTECT,related_name='created_purchases'); confirmed_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='confirmed_purchases'); received_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='received_purchases'); cancelled_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='cancelled_purchases'); confirmed_at=models.DateTimeField(null=True,blank=True); received_at=models.DateTimeField(null=True,blank=True); cancelled_at=models.DateTimeField(null=True,blank=True); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
 @property
 def subtotal(self): return sum((x.line_total for x in self.lines.all()),Decimal('0.000'))
 total=subtotal
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_purchase_public_id
  if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists(): raise ValidationError('Purchase public_id is immutable.')
  if not self.public_id:self.public_id=generate_purchase_public_id()
  return super().save(*a,**kw)

class PurchaseLine(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False); public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True); purchase=models.ForeignKey(Purchase,on_delete=models.PROTECT,related_name='lines'); product=models.ForeignKey('catalog.Product',null=True,blank=True,on_delete=models.PROTECT); variant=models.ForeignKey('catalog.ProductVariant',null=True,blank=True,on_delete=models.PROTECT); quantity=models.DecimalField(max_digits=14,decimal_places=3); unit_cost=models.DecimalField(max_digits=14,decimal_places=2); line_total=models.DecimalField(max_digits=16,decimal_places=2,editable=False); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  constraints=[models.CheckConstraint(condition=Q(product__isnull=False,variant__isnull=True)|Q(product__isnull=True,variant__isnull=False),name='purchase_line_exactly_one_target'),models.CheckConstraint(condition=Q(quantity__gt=0),name='purchase_line_quantity_positive'),models.CheckConstraint(condition=Q(unit_cost__gte=0),name='purchase_line_cost_nonnegative')]
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_purchase_line_public_id
  if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists(): raise ValidationError('PurchaseLine public_id is immutable.')
  if not self.public_id:self.public_id=generate_purchase_line_public_id()
  self.line_total=self.quantity*self.unit_cost
  return super().save(*a,**kw)
