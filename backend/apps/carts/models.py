"""Buyer-owned, pre-order shopping carts."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.businesses.identifiers import generate_public_id


def normalize_cart_name(value: str) -> str:
    """Return the deterministic key used to compare cart names."""
    return " ".join((value or "").split()).casefold()


class Cart(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        LOCKED = "LOCKED", "Locked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    buyer = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT, related_name="carts")
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="carts")
    name = models.CharField(max_length=120)
    name_normalized = models.CharField(max_length=120, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        "accounts.CarriIdentity", null=True, blank=True, on_delete=models.PROTECT,
        related_name="locked_carts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "reference")
        constraints = [
            models.UniqueConstraint(
                fields=("buyer", "business", "name_normalized"),
                name="cart_buyer_business_name_normalized_unique",
            ),
        ]

    def clean(self):
        super().clean()
        self.name = " ".join((self.name or "").split())
        self.name_normalized = normalize_cart_name(self.name)
        if not self.name_normalized:
            raise ValidationError({"name": "Le nom du panier ne peut pas être vide."})

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = generate_public_id("CT")
        self.full_clean()
        return super().save(*args, **kwargs)


class CartItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="cart_items")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        constraints = [
            models.UniqueConstraint(fields=("cart", "product"), name="cart_item_cart_product_unique"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="cart_item_quantity_positive"),
        ]

    def clean(self):
        super().clean()
        if self.cart_id and self.product_id and self.cart.business_id != self.product.business_id:
            raise ValidationError({"product": "Le produit n'appartient pas à l'entreprise du panier."})
