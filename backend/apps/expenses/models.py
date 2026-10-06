import uuid
from django.db import models
class ExpenseCategory(models.Model):
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT,related_name='expense_categories');code=models.CharField(max_length=40);name=models.CharField(max_length=100);description=models.TextField(blank=True);is_system=models.BooleanField(default=False);is_active=models.BooleanField(default=True);sort_order=models.PositiveIntegerField(default=0);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 class Meta:constraints=[models.UniqueConstraint(fields=('business','code'),name='expense_category_business_code')];ordering=('sort_order','name')
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_expense_category_public_id
  if not self.public_id:self.public_id=generate_expense_category_public_id()
  return super().save(*a,**kw)
class Expense(models.Model):
 class Status(models.TextChoices):ACTIVE='ACTIVE','Active';CANCELLED='CANCELLED','Cancelled'
 id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False);public_id=models.CharField(max_length=12,unique=True,editable=False);business=models.ForeignKey('businesses.Business',on_delete=models.PROTECT);category=models.ForeignKey(ExpenseCategory,on_delete=models.PROTECT);amount=models.DecimalField(max_digits=16,decimal_places=2);currency=models.CharField(max_length=3,choices=(('CDF','CDF'),('USD','USD')));payment_method=models.CharField(max_length=20);expense_date=models.DateField();description=models.CharField(max_length=500);reference=models.CharField(max_length=120,blank=True);status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE);created_by=models.ForeignKey('accounts.CarriIdentity',on_delete=models.PROTECT,related_name='expenses');cancelled_by=models.ForeignKey('accounts.CarriIdentity',null=True,blank=True,on_delete=models.PROTECT,related_name='cancelled_expenses');cancelled_at=models.DateTimeField(null=True,blank=True);cancellation_reason=models.CharField(max_length=500,blank=True);created_at=models.DateTimeField(auto_now_add=True);updated_at=models.DateTimeField(auto_now=True)
 class Meta:ordering=('-expense_date','-created_at')
 def save(self,*a,**kw):
  from apps.businesses.identifiers import generate_expense_public_id
  if not self.public_id:self.public_id=generate_expense_public_id()
  return super().save(*a,**kw)
