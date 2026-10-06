import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone
class Receivable(models.Model):
 class Status(models.TextChoices):OPEN='OPEN','Open';PARTIALLY_PAID='PARTIALLY_PAID','Partially paid';PAID='PAID','Paid'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);sale=models.OneToOneField('sales.Sale',on_delete=models.PROTECT,related_name='receivable');customer=models.ForeignKey('sales.Customer',on_delete=models.PROTECT);currency=models.CharField(max_length=3);original_amount=models.DecimalField(max_digits=16,decimal_places=2);status=models.CharField(max_length=20,choices=Status.choices,default=Status.OPEN);due_date=models.DateField(null=True,blank=True);notes=models.TextField(blank=True);settled_at=models.DateTimeField(null=True,blank=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 @property
 def paid_amount(self):return sum((x.amount for x in self.payments.all()),Decimal('0.00'))
 @property
 def balance(self):return self.original_amount-self.paid_amount
 @property
 def is_overdue(self):return bool(self.due_date and self.due_date<timezone.localdate() and self.balance>0)
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_receivable_public_id
  if not self.public_id:self.public_id=generate_receivable_public_id()
  return super().save(*a,**kw)
class ReceivablePayment(models.Model):
 class Method(models.TextChoices):CASH='CASH','Cash';MOBILE_MONEY='MOBILE_MONEY','Mobile money';BANK_TRANSFER='BANK_TRANSFER','Bank transfer';CARD='CARD','Card';OTHER='OTHER','Other'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False,db_index=True);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);receivable=models.ForeignKey(Receivable,on_delete=models.PROTECT,related_name='payments');amount=models.DecimalField(max_digits=16,decimal_places=2);payment_method=models.CharField(max_length=20,choices=Method.choices);reference=models.CharField(max_length=120,blank=True);notes=models.TextField(blank=True);received_by=models.ForeignKey('accounts.CarriIdentity',on_delete=models.PROTECT);paid_at=models.DateTimeField(auto_now_add=True);created_at=models.DateTimeField(auto_now_add=True)
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_receivable_payment_public_id
  if self.pk and type(self).objects.filter(pk=self.pk).exists():raise ValueError('Payment immutable')
  if not self.public_id:self.public_id=generate_receivable_payment_public_id()
  return super().save(*a,**kw)
