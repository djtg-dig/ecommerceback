"""Procurement workflow and atomic, idempotent inventory reception."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.inventory.models import InventoryItem, StockMovement
from apps.inventory.services import apply_stock_movement, create_inventory_item, validate_inventory_target
from .models import Purchase

def validate_line_target(purchase, product=None, variant=None):
 if bool(product)==bool(variant): raise ValidationError('Choisir exactement un produit ou une variante.')
 validate_inventory_target(business=purchase.business,product=product,variant=variant)

def transition(purchase, action, actor):
 """Lock and apply only documented Purchase status transitions."""
 with transaction.atomic():
  p=Purchase.objects.select_for_update().get(pk=purchase.pk); now=timezone.now()
  if action=='confirm':
   if p.status!=Purchase.Status.DRAFT or not p.lines.exists(): raise ValidationError('Seul un brouillon avec lignes peut être confirmé.')
   p.status=Purchase.Status.CONFIRMED;p.confirmed_at=now;p.confirmed_by=actor
  elif action=='cancel':
   if p.status not in {Purchase.Status.DRAFT,Purchase.Status.CONFIRMED}: raise ValidationError('Cet achat ne peut pas être annulé.')
   if p.payments.filter(reversed_at__isnull=True).exists(): raise ValidationError('Supplier payments must be reversed before cancellation.')
   p.status=Purchase.Status.CANCELLED;p.cancelled_at=now;p.cancelled_by=actor
  else: raise ValidationError('Transition inconnue.')
  p.save(update_fields=('status','confirmed_at','confirmed_by','cancelled_at','cancelled_by','updated_at'));return p

def receive_purchase(purchase, actor):
 """Receive every line once, creating zero-balance inventory when absent."""
 with transaction.atomic():
  p=Purchase.objects.select_for_update().select_related('business').get(pk=purchase.pk)
  if p.status!=Purchase.Status.CONFIRMED: raise ValidationError('Seul un achat confirmé peut être reçu.')
  lines=list(p.lines.select_related('product','variant__product').order_by('public_id'))
  if not lines: raise ValidationError('Un achat doit avoir des lignes.')
  for line in lines:
   validate_line_target(p,line.product,line.variant)
   item=InventoryItem.objects.filter(product=line.product) if line.product else InventoryItem.objects.filter(variant=line.variant)
   item=item.first()
   if not item: item=create_inventory_item(business=p.business,product=line.product,variant=line.variant)
   apply_stock_movement(inventory_item=item,movement_type=StockMovement.Type.IN,performed_by=actor,quantity=line.quantity,reason=f'Purchase {p.public_id}',reference_type='PURCHASE',reference_id=line.public_id)
   target=line.variant or line.product; target.cost_price=line.unit_cost; target.save(update_fields=('cost_price','updated_at'))
  p.status=Purchase.Status.RECEIVED;p.received_at=timezone.now();p.received_by=actor;p.save(update_fields=('status','received_at','received_by','updated_at'));return p

import hashlib,json
from apps.common.choices import PaymentMethod
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement, reverse_movement
from .models import SupplierPayment
class SupplierPaymentIdempotencyConflict(ValidationError):pass
def add_supplier_payment(purchase,actor,amount,payment_method,idempotency_key=''):
 """Lock confirmed/received purchases so payment and Finance outflow are atomic."""
 if amount is None or amount<=0 or payment_method not in PaymentMethod.values:raise ValidationError('Invalid supplier payment.')
 with transaction.atomic():
  p=Purchase.objects.select_for_update().get(pk=purchase.pk)
  if p.status not in {Purchase.Status.CONFIRMED,Purchase.Status.RECEIVED}:raise ValidationError('Only confirmed or received purchases can be paid.')
  fp=hashlib.sha256(json.dumps({'purchase':p.public_id,'amount':str(amount),'payment_method':payment_method},sort_keys=True).encode()).hexdigest()
  if idempotency_key:
   old=SupplierPayment.objects.filter(purchase=p,idempotency_key=idempotency_key).first()
   if old:
    if old.idempotency_fingerprint!=fp:raise SupplierPaymentIdempotencyConflict('Idempotency key conflicts with a different payment.')
    return old
  if amount>p.balance:raise ValidationError('Payment exceeds purchase balance.')
  pay=SupplierPayment.objects.create(purchase=p,amount=amount,payment_method=payment_method,created_by=actor,idempotency_key=idempotency_key,idempotency_fingerprint=fp if idempotency_key else '')
  create_financial_movement(business=p.business,direction=FinancialMovement.Direction.OUTFLOW,amount=amount,payment_method=payment_method,event_type=FinancialMovement.EventType.SUPPLIER_PAYMENT,created_by=actor,supplier_payment=pay,occurred_at=pay.paid_at)
  return pay
def reverse_supplier_payment(payment,actor,reason):
 """Reverse the financial outflow without changing received stock."""
 with transaction.atomic():
  pay=SupplierPayment.objects.select_for_update().get(pk=payment.pk)
  if pay.is_reversed:raise ValidationError('Supplier payment already reversed.')
  m=FinancialMovement.objects.select_for_update().get(supplier_payment=pay)
  # Finance reversal accepts the supplier event using its dedicated event type.
  if not reason or not reason.strip():raise ValidationError('A reversal reason is required.')
  FinancialMovement.objects.create(business=m.business,direction=FinancialMovement.Direction.INFLOW,amount=m.amount,currency=m.currency,payment_method=m.payment_method,event_type=FinancialMovement.EventType.SUPPLIER_PAYMENT_REVERSAL,occurred_at=timezone.now(),created_by=actor,reason=reason.strip(),reversal_of=m)
  pay.reversed_at=timezone.now();pay.reversed_by=actor;pay.reversal_reason=reason.strip();pay.save(update_fields=('reversed_at','reversed_by','reversal_reason'));return pay
