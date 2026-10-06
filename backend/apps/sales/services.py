from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from apps.inventory.models import InventoryItem,StockMovement
from apps.inventory.services import apply_stock_movement,validate_inventory_target
from .models import Sale
def target(sale,product=None,variant=None):
 if bool(product)==bool(variant):raise ValidationError('Choose one target')
 validate_inventory_target(business=sale.business,product=product,variant=variant)
def complete(sale,actor,amount_paid=None,payment_method="CASH"):
 """Atomically consume stock and append SALE movements once."""
 with transaction.atomic():
  s=Sale.objects.select_for_update().get(pk=sale.pk)
  if s.status!='DRAFT' or not s.lines.exists():raise ValidationError('Only non-empty drafts complete.')
  total=s.total; paid=total if amount_paid is None else amount_paid
  if paid < 0 or paid > total: raise ValidationError('Invalid paid amount.')
  if paid < total and not s.customer_id: raise ValidationError('Customer is required for credit.')
  lines=list(s.lines.select_related('product','variant__product').order_by('public_id'))
  for l in lines:
   target(s,l.product,l.variant);item=(InventoryItem.objects.filter(product=l.product) if l.product else InventoryItem.objects.filter(variant=l.variant)).first()
   if not item:raise ValidationError('Inventory item missing.')
   cost=(l.variant.effective_cost_price if l.variant else l.product.cost_price);l.unit_cost_snapshot=cost;l.save(update_fields=('unit_cost_snapshot','updated_at'))
   apply_stock_movement(inventory_item=item,movement_type=StockMovement.Type.SALE,performed_by=actor,quantity=l.quantity,reference_type='SALE',reference_id=l.public_id,reason=f'Sale {s.public_id}')
  if paid < total:
   from apps.receivables.models import Receivable, ReceivablePayment
   r=Receivable.objects.create(business=s.business,sale=s,customer=s.customer,currency=s.currency,original_amount=total,status='OPEN')
   if paid > 0:
    ReceivablePayment.objects.create(business=s.business,receivable=r,amount=paid,payment_method=payment_method,received_by=actor)
    r.status='PARTIALLY_PAID';r.save(update_fields=('status','updated_at'))
  s.status='COMPLETED';s.completed_at=timezone.now();s.completed_by=actor;s.save(update_fields=('status','completed_at','completed_by','updated_at'));return s
def cancel(sale,actor):
 with transaction.atomic():
  s=Sale.objects.select_for_update().get(pk=sale.pk)
  if s.status!='DRAFT':raise ValidationError('Only drafts cancel.')
  s.status='CANCELLED';s.cancelled_at=timezone.now();s.cancelled_by=actor;s.save(update_fields=('status','cancelled_at','cancelled_by','updated_at'));return s
