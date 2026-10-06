"""Transactional stock mutations and sellable-target invariants."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import InventoryItem, StockMovement

MANUAL_MOVEMENT_TYPES = {StockMovement.Type.IN, StockMovement.Type.OUT, StockMovement.Type.ADJUSTMENT}


def validate_inventory_target(*, business, product=None, variant=None) -> None:
    """Ensure exactly one active sellable target belongs to ``business``.

    A simple product cannot own stock while it has active variants. This avoids
    concurrent product and variant balances. Creating a variant after product
    stock exists is also refused by ``ensure_can_create_variant``; operators
    must first resolve the product balance explicitly with an adjustment.
    """
    if bool(product) == bool(variant):
        raise ValidationError("Choisir exactement un produit ou une variante.")
    if product:
        if product.business_id != business.id:
            raise ValidationError({"product": "Le produit n'appartient pas à ce commerce."})
        if product.status == "ARCHIVED":
            raise ValidationError({"product": "Un produit archivé ne peut pas recevoir de stock."})
        if product.variants.filter(status="ACTIVE").exists():
            raise ValidationError({"product": "Un produit avec variantes actives doit être stocké par variante."})
    if variant:
        if variant.product.business_id != business.id:
            raise ValidationError({"variant": "La variante n'appartient pas à ce commerce."})
        if variant.status == "ARCHIVED" or variant.product.status == "ARCHIVED":
            raise ValidationError({"variant": "Une variante archivée ne peut pas recevoir de stock."})


def ensure_can_create_variant(product) -> None:
    """Refuse a topology change that would leave an ambiguous product balance."""
    if InventoryItem.objects.filter(product=product).exists():
        raise ValidationError("Résoudre le stock produit avant de créer des variantes.")


def create_inventory_item(*, business, product=None, variant=None, low_stock_threshold=None):
    """Create a zero-balance item with bounded public-ID collision retries."""
    from apps.businesses.identifiers import generate_inventory_item_public_id

    validate_inventory_target(business=business, product=product, variant=variant)
    for _ in range(5):
        try:
            with transaction.atomic():
                return InventoryItem.objects.create(
                    public_id=generate_inventory_item_public_id(), business=business,
                    product=product, variant=variant, low_stock_threshold=low_stock_threshold,
                )
        except IntegrityError as exc:
            if "public_id" not in str(exc):
                raise
    raise RuntimeError("Impossible de générer un identifiant inventaire unique.")


def apply_stock_movement(*, inventory_item, movement_type, performed_by, quantity=None, target_quantity=None, reason="", reference_type=None, reference_id=None):
    """Atomically update one balance and append its immutable movement event.

    The row lock is acquired before reading the balance. ``IN`` and ``OUT``
    take positive quantities; adjustment receives an absolute target quantity.
    Quantity update and event insertion share one transaction, so neither can
    persist without the other.
    """
    if movement_type not in MANUAL_MOVEMENT_TYPES:
        raise ValidationError({"type": "Seuls IN, OUT et ADJUSTMENT sont autorisés manuellement."})
    with transaction.atomic():
        item = InventoryItem.objects.select_for_update(of=("self",)).select_related("product", "variant__product").get(pk=inventory_item.pk)
        target = item.variant or item.product
        validate_inventory_target(business=item.business, product=item.product, variant=item.variant)
        before = item.quantity
        available = item.available_quantity
        if movement_type == StockMovement.Type.ADJUSTMENT:
            if target_quantity is None or target_quantity < 0:
                raise ValidationError({"target_quantity": "La quantité cible doit être positive ou nulle."})
            after = target_quantity
            delta = after - before
        else:
            if quantity is None or quantity <= 0:
                raise ValidationError({"quantity": "La quantité doit être strictement positive."})
            if movement_type == StockMovement.Type.IN:
                after, delta = before + quantity, quantity
            else:
                if quantity > available:
                    raise ValidationError({"quantity": "La sortie dépasse le stock disponible."})
                after, delta = before - quantity, -quantity
        if after < item.reserved_quantity:
            raise ValidationError({"quantity": "L'opération descend sous la quantité réservée."})
        item.quantity = after
        item.save(update_fields=("quantity", "updated_at"))
        return StockMovement.objects.create(
            business=item.business, inventory_item=item, movement_type=movement_type,
            quantity=delta, quantity_before=before, quantity_after=after,
            reason=reason or "", performed_by=performed_by, reference_type=reference_type, reference_id=reference_id,
        )
