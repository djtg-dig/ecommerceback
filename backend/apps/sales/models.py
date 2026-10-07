import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
class Customer(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);name=models.CharField(max_length=200);phone=models.CharField(max_length=40,blank=True);email=models.EmailField(blank=True);address=models.TextField(blank=True);notes=models.TextField(blank=True);is_active=models.BooleanField(default=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_customer_public_id
  if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists():raise ValidationError('Customer public_id immutable')
  if not self.public_id:self.public_id=generate_customer_public_id()
  return super().save(*a,**kw)
class Sale(models.Model):
 class Status(models.TextChoices):DRAFT='DRAFT','Draft';COMPLETED='COMPLETED','Completed';CANCELLED='CANCELLED','Cancelled'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);customer=models.ForeignKey(Customer,null=True,blank=True,on_delete=models.PROTECT);status=models.CharField(max_length=12,choices=Status.choices,default=Status.DRAFT);currency=models.CharField(max_length=3,choices=(('CDF','CDF'),('USD','USD')));reference=models.CharField(max_length=120,blank=True);notes=models.TextField(blank=True);created_by=models.ForeignKey('accounts.CarriIdentity',on_delete=models.PROTECT,related_name='sales_created');completed_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='sales_completed');cancelled_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='sales_cancelled');completed_at=models.DateTimeField(null=True,blank=True);cancelled_at=models.DateTimeField(null=True,blank=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 @property
 def total(self):return sum((x.line_total for x in self.lines.all()),Decimal('0.00'))
 subtotal=total
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_sale_public_id
  if not self.public_id:self.public_id=generate_sale_public_id()
  return super().save(*a,**kw)
class SaleLine(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);sale=models.ForeignKey(Sale,on_delete=models.PROTECT,related_name='lines');product=models.ForeignKey('catalog.Product',null=True,blank=True,on_delete=models.PROTECT);variant=models.ForeignKey('catalog.ProductVariant',null=True,blank=True,on_delete=models.PROTECT);quantity=models.DecimalField(max_digits=14,decimal_places=3);unit_price=models.DecimalField(max_digits=14,decimal_places=2);unit_cost_snapshot=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True);line_total=models.DecimalField(max_digits=16,decimal_places=2,editable=False);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 class Meta:constraints=[models.CheckConstraint(condition=Q(product__isnull=False,variant__isnull=True)|Q(product__isnull=True,variant__isnull=False),name='sale_line_xor'),models.CheckConstraint(condition=Q(quantity__gt=0),name='sale_line_qty'),models.UniqueConstraint(fields=('sale','product'),condition=Q(product__isnull=False),name='sale_line_unique_product'),models.UniqueConstraint(fields=('sale','variant'),condition=Q(variant__isnull=False),name='sale_line_unique_variant')]
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_sale_line_public_id
  if not self.public_id:self.public_id=generate_sale_line_public_id()
  self.line_total=self.quantity*self.unit_price;return super().save(*a,**kw)


class SaleReturn(models.Model):
 class Status(models.TextChoices): POSTED='POSTED','Posted'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);sale=models.ForeignKey(Sale,on_delete=models.PROTECT,related_name='returns');business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);customer=models.ForeignKey(Customer,null=True,blank=True,on_delete=models.PROTECT);status=models.CharField(max_length=12,choices=Status.choices,default=Status.POSTED);reason=models.TextField(blank=True);returned_at=models.DateTimeField();created_by=models.ForeignKey('accounts.CarriIdentity',on_delete=models.PROTECT);idempotency_key=models.CharField(max_length=255);idempotency_fingerprint=models.CharField(max_length=64);receivable_credit_amount=models.DecimalField(max_digits=16,decimal_places=2,default=0);refund_amount=models.DecimalField(max_digits=16,decimal_places=2,default=0);refund_payment_method=models.ForeignKey('businesses.BusinessPaymentMethod',null=True,blank=True,on_delete=models.PROTECT);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 class Meta:
  ordering=('-returned_at','-created_at');constraints=[models.CheckConstraint(condition=Q(receivable_credit_amount__gte=0)&Q(refund_amount__gte=0),name='sale_return_amounts_nonnegative'),models.UniqueConstraint(fields=('business','idempotency_key'),name='sale_return_business_idempotency_key')]
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_sale_return_public_id
  if not self._state.adding:raise ValidationError('Sale returns are immutable.')
  if not self.public_id:self.public_id=generate_sale_return_public_id()
  self.full_clean();return super().save(*a,**kw)
 def delete(self,*a,**kw):raise ValidationError('Sale returns cannot be deleted.')

class SaleReturnLine(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);sale_return=models.ForeignKey(SaleReturn,on_delete=models.PROTECT,related_name='lines');sale_line=models.ForeignKey(SaleLine,on_delete=models.PROTECT,related_name='return_lines');quantity=models.DecimalField(max_digits=14,decimal_places=3);unit_price_snapshot=models.DecimalField(max_digits=14,decimal_places=2);unit_cost_snapshot=models.DecimalField(max_digits=14,decimal_places=2,null=True,blank=True);line_total=models.DecimalField(max_digits=16,decimal_places=2);created_at=models.DateTimeField(auto_now_add=True)
 class Meta:constraints=[models.CheckConstraint(condition=Q(quantity__gt=0),name='sale_return_line_quantity_positive'),models.UniqueConstraint(fields=('sale_return','sale_line'),name='sale_return_one_line_per_sale_line')]
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_sale_return_line_public_id
  if not self._state.adding:raise ValidationError('Sale return lines are immutable.')
  if not self.public_id:self.public_id=generate_sale_return_line_public_id()
  self.full_clean();return super().save(*a,**kw)
 def delete(self,*a,**kw):raise ValidationError('Sale return lines cannot be deleted.')
