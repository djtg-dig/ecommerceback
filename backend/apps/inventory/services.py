"""Transactional stock mutations and sellable-target invariants."""

import hashlib
import json

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import InventoryItem, StockMovement

MANUAL_MOVEMENT_TYPES = {StockMovement.Type.IN, StockMovement.Type.OUT, StockMovement.Type.ADJUSTMENT}
STOCK_DECIMAL_PLACES = 3
STOCK_MAX_INTEGER_DIGITS = 11


class StockMovementIdempotencyConflict(ValidationError):
    """Raised when one retry key is reused for a different stock intent."""


class InsufficientStockError(ValidationError):
    """A safe, structured stock conflict for commercial clients."""

    def __init__(self, *, inventory_item, requested_quantity):
        self.inventory_item = inventory_item
        self.requested_quantity = requested_quantity
        self.available_quantity = inventory_item.available_quantity
        super().__init__("Stock insuffisant.")


def normalize_stock_quantity(value, *, field):
    """Convertit une quantité externe en ``Decimal`` compatible avec le stock.

    Les services sont aussi appelés hors serializers DRF (réceptions, ventes et
    scripts). Cette normalisation évite que ces appelants puissent contourner
    les garanties du ``DecimalField`` ou provoquer une erreur de type interne.
    """
    if isinstance(value, bool):
        raise ValidationError({field: "La quantité doit être un nombre valide."})
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "La quantité doit être un nombre valide."}) from None
    if not normalized.is_finite():
        raise ValidationError({field: "La quantité doit être un nombre fini."})
    if normalized.as_tuple().exponent < -STOCK_DECIMAL_PLACES:
        raise ValidationError({field: "La quantité ne peut pas avoir plus de 3 décimales."})
    if normalized and normalized.adjusted() >= STOCK_MAX_INTEGER_DIGITS:
        raise ValidationError({field: "La quantité dépasse la précision maximale du stock."})
    return normalized


def movement_fingerprint(*, inventory_item, movement_type, quantity, target_quantity, reason):
    def canonical(value):
        if value is None:
            return None
        return format(Decimal(str(value)).normalize(), "f")

    payload = {
        "inventory_item": inventory_item.public_id,
        "movement_type": movement_type,
        "quantity": canonical(quantity),
        "target_quantity": canonical(target_quantity),
        "reason": reason or "",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_inventory_target(*, business, product=None, variant=None, allow_archived_target=False) -> None:
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
        if product.status == "ARCHIVED" and not allow_archived_target:
            raise ValidationError({"product": "Un produit archivé ne peut pas recevoir de stock."})
        if product.variants.filter(status="ACTIVE").exists():
            raise ValidationError({"product": "Un produit avec variantes actives doit être stocké par variante."})
    if variant:
        if variant.product.business_id != business.id:
            raise ValidationError({"variant": "La variante n'appartient pas à ce commerce."})
        if (variant.status == "ARCHIVED" or variant.product.status == "ARCHIVED") and not allow_archived_target:
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


def apply_stock_movement(*, inventory_item, movement_type, performed_by, quantity=None, target_quantity=None, reason="", reference_type=None, reference_id=None, allow_archived_target=False, idempotency_key=""):
    """Atomically update one balance and append its immutable movement event.

    The row lock is acquired before reading the balance. ``IN`` and ``OUT``
    take positive quantities; adjustment receives an absolute target quantity.
    Quantity update and event insertion share one transaction, so neither can
    persist without the other.
    """
    if movement_type not in MANUAL_MOVEMENT_TYPES and not (movement_type == StockMovement.Type.SALE and reference_type == 'SALE') and not (movement_type == StockMovement.Type.RETURN and reference_type == 'SALE_RETURN_LINE'):
        raise ValidationError({"type": "Seuls IN, OUT et ADJUSTMENT sont autorisés manuellement."})
    if quantity is not None:
        quantity = normalize_stock_quantity(quantity, field="quantity")
    if target_quantity is not None:
        target_quantity = normalize_stock_quantity(target_quantity, field="target_quantity")
    with transaction.atomic():
        item = InventoryItem.objects.select_for_update(of=("self",)).select_related("product", "variant__product").get(pk=inventory_item.pk)
        fingerprint = movement_fingerprint(
            inventory_item=item,
            movement_type=movement_type,
            quantity=quantity,
            target_quantity=target_quantity,
            reason=reason,
        ) if idempotency_key else ""
        if idempotency_key:
            existing = StockMovement.objects.filter(
                business=item.business,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                if existing.idempotency_fingerprint != fingerprint:
                    raise StockMovementIdempotencyConflict(
                        "La clé d’idempotence correspond à un autre mouvement."
                    )
                existing._idempotent_replay = True
                return existing
        validate_inventory_target(business=item.business, product=item.product, variant=item.variant, allow_archived_target=allow_archived_target)
        unit = item.variant.product.unit_of_measure if item.variant_id else item.product.unit_of_measure
        value_to_validate = target_quantity if movement_type == StockMovement.Type.ADJUSTMENT else quantity
        if value_to_validate is not None and not unit.allows_decimal_quantity and value_to_validate != value_to_validate.to_integral_value():
            field = "target_quantity" if movement_type == StockMovement.Type.ADJUSTMENT else "quantity"
            raise ValidationError({field: "Cette unité doit être stockée en quantité entière."})
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
            if movement_type in {StockMovement.Type.IN, StockMovement.Type.RETURN}:
                after, delta = before + quantity, quantity
            else:
                if quantity > available:
                    raise InsufficientStockError(inventory_item=item, requested_quantity=quantity)
                after, delta = before - quantity, -quantity
        normalize_stock_quantity(after, field="quantity")
        if after < item.reserved_quantity:
            raise ValidationError({"quantity": "L'opération descend sous la quantité réservée."})
        item.quantity = after
        if allow_archived_target and movement_type == StockMovement.Type.RETURN:
            InventoryItem.objects.filter(pk=item.pk).update(quantity=after)
        else:
            item.save(update_fields=("quantity", "updated_at"))
        try:
            return StockMovement.objects.create(
                business=item.business, inventory_item=item, movement_type=movement_type,
                quantity=delta, quantity_before=before, quantity_after=after,
                reason=reason or "", performed_by=performed_by, reference_type=reference_type, reference_id=reference_id,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=fingerprint,
            )
        except IntegrityError as exc:
            if idempotency_key:
                raise StockMovementIdempotencyConflict(
                    "La clé d’idempotence est déjà utilisée."
                ) from exc
            raise
