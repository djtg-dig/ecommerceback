from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Receivable,ReceivablePayment
def add_payment(receivable,actor,amount,payment_method,reference='',notes=''):
 """Lock balance, prevent overpayment, append immutable internal payment."""
 with transaction.atomic():
  r=Receivable.objects.select_for_update().get(pk=receivable.pk)
  if r.status=='PAID' or amount<=0 or amount>r.balance:raise ValidationError('Invalid payment.')
  p=ReceivablePayment.objects.create(business=r.business,receivable=r,amount=amount,payment_method=payment_method,reference=reference,notes=notes,received_by=actor)
  bal=r.balance
  if bal==0:r.status='PAID';r.settled_at=timezone.now()
  else:r.status='PARTIALLY_PAID'
  r.save(update_fields=('status','settled_at','updated_at'));return p
