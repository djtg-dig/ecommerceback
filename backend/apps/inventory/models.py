"""Persistent inventory balances and immutable stock movements."""

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class InventoryItem(models.Model):
    """One stock balance for exactly one simple product or one variant."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="inventory_items")
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_items")
    variant = models.ForeignKey("catalog.ProductVariant", null=True, blank=True, on_delete=models.PROTECT, related_name="inventory_items")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    reserved_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))
    low_stock_threshold = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("public_id",)
        constraints = [
            models.CheckConstraint(
                condition=(Q(product__isnull=False, variant__isnull=True) | Q(product__isnull=True, variant__isnull=False)),
                name="inventory_item_exactly_one_sellable",
            ),
            models.UniqueConstraint(fields=("product",), condition=Q(product__isnull=False), name="inventory_item_unique_product"),
            models.UniqueConstraint(fields=("variant",), condition=Q(variant__isnull=False), name="inventory_item_unique_variant"),
            models.CheckConstraint(condition=Q(quantity__gte=0), name="inventory_item_quantity_nonnegative"),
            models.CheckConstraint(condition=Q(reserved_quantity__gte=0), name="inventory_item_reserved_nonnegative"),
            models.CheckConstraint(condition=Q(reserved_quantity__lte=models.F("quantity")), name="inventory_item_reserved_lte_quantity"),
            models.CheckConstraint(condition=Q(low_stock_threshold__isnull=True) | Q(low_stock_threshold__gte=0), name="inventory_item_threshold_nonnegative"),
        ]

    def __str__(self) -> str:
        return self.public_id

    @property
    def available_quantity(self):
        """Return unreserved stock; reservation workflows will own this later."""
        return self.quantity - self.reserved_quantity

    @property
    def is_low_stock(self):
        """Return whether available quantity reaches the optional alert threshold."""
        return self.low_stock_threshold is not None and self.available_quantity <= self.low_stock_threshold

    def clean(self):
        """Defend sellable ownership and product/variant stock-source invariants."""
        super().clean()
        if bool(self.product_id) == bool(self.variant_id):
            raise ValidationError("Un inventaire doit viser exactement un produit ou une variante.")
        if self.product_id:
            if self.product.business_id != self.business_id:
                raise ValidationError({"product": "Le produit doit appartenir au même commerce."})
            if self.product.status == "ARCHIVED":
                raise ValidationError({"product": "Un produit archivé ne peut pas recevoir de stock."})
            if self.product.variants.filter(status="ACTIVE").exists():
                raise ValidationError({"product": "Un produit avec variantes actives doit être stocké par variante."})
        if self.variant_id:
            if self.variant.product.business_id != self.business_id:
                raise ValidationError({"variant": "La variante doit appartenir au même commerce."})
            if self.variant.status == "ARCHIVED" or self.variant.product.status == "ARCHIVED":
                raise ValidationError({"variant": "Une variante ou son produit archivé ne peut pas recevoir de stock."})

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_inventory_item_public_id

        if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists():
            raise ValidationError({"public_id": "L'identifiant public inventaire est immuable."})
        if not self.public_id:
            self.public_id = generate_inventory_item_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)


class StockMovement(models.Model):
    """Immutable event recording one inventory balance transition."""

    class Type(models.TextChoices):
        IN = "IN", "Entrée"
        OUT = "OUT", "Sortie"
        ADJUSTMENT = "ADJUSTMENT", "Ajustement"
        TRANSFER = "TRANSFER", "Transfert"
        SALE = "SALE", "Vente"
        RETURN = "RETURN", "Retour"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="stock_movements")
    inventory_item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=12, choices=Type.choices)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_before = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=500, blank=True)
    reference_type = models.CharField(max_length=40, null=True, blank=True, editable=False)
    reference_id = models.CharField(max_length=128, null=True, blank=True, editable=False)
    performed_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT, related_name="stock_movements")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-public_id")
        constraints = [
            models.CheckConstraint(condition=Q(quantity_before__gte=0), name="stock_movement_before_nonnegative"),
            models.CheckConstraint(condition=Q(quantity_after__gte=0), name="stock_movement_after_nonnegative"),
        ]

    def __str__(self) -> str:
        return self.public_id

    def clean(self):
        """Ensure a movement cannot be attached to another business's item."""
        super().clean()
        if self.inventory_item_id and self.business_id != self.inventory_item.business_id:
            raise ValidationError({"business": "Le mouvement et son inventaire doivent partager le même commerce."})

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_stock_movement_public_id

        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Un mouvement de stock est immuable.")
        if not self.public_id:
            self.public_id = generate_stock_movement_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)
