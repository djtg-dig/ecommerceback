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
