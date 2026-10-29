"""Transactional cart mutations and their invariants."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Cart, CartItem, normalize_cart_name


class CartLockedError(Exception):
    """Raised whenever a buyer tries to mutate a locked cart."""


def require_mutable(cart: Cart) -> None:
    if cart.status != Cart.Status.DRAFT:
        raise CartLockedError()


def normalize_quantity(product, value) -> Decimal:
    """Validate a positive cart quantity against the product's unit."""
    if isinstance(value, bool):
        raise ValidationError({"quantity": "La quantité doit être un nombre valide."})
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantity": "La quantité doit être un nombre valide."}) from None
    if not quantity.is_finite() or quantity <= 0:
        raise ValidationError({"quantity": "La quantité doit être strictement positive."})
    if quantity.as_tuple().exponent < -3 or quantity.adjusted() >= 11:
        raise ValidationError({"quantity": "La quantité dépasse la précision autorisée."})
    if not product.unit_of_measure.allows_decimal_quantity and quantity != quantity.to_integral_value():
        raise ValidationError({"quantity": "Cette unité exige une quantité entière."})
    return quantity


def create_cart(*, buyer, business, name):
    cart = Cart(buyer=buyer, business=business, name=name)
    cart.full_clean()
    return cart


def create_default_cart(*, buyer, business):
    """Serialize default-name allocation per buyer to prevent duplicate names."""
    with transaction.atomic():
        type(buyer).objects.select_for_update().get(pk=buyer.pk)
        existing = set(Cart.objects.filter(buyer=buyer, business=business).values_list("name_normalized", flat=True))
        number = 1
        while True:
            name = "Mon panier" if number == 1 else f"Mon panier {number}"
            if normalize_cart_name(name) not in existing:
                break
            number += 1
        for _ in range(5):
            cart = Cart(buyer=buyer, business=business, name=name)
            try:
                cart.save()
                return cart
            except IntegrityError:
                number += 1
                name = f"Mon panier {number}"
    raise RuntimeError("Impossible de créer un panier automatiquement.")


def add_product(*, cart, product, quantity):
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        require_mutable(cart)
        if cart.business_id != product.business_id:
            raise ValidationError({"product": "Le produit n'appartient pas à l'entreprise du panier."})
        quantity = normalize_quantity(product, quantity)
        item = CartItem.objects.select_for_update().filter(cart=cart, product=product).first()
        if item:
            item.quantity = normalize_quantity(product, item.quantity + quantity)
            item.save(update_fields=("quantity", "updated_at"))
        else:
            item = CartItem.objects.create(cart=cart, product=product, quantity=quantity)
        return item


def set_item_quantity(*, cart, product, quantity):
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        require_mutable(cart)
        item = CartItem.objects.select_for_update().filter(cart=cart, product=product).first()
        if not item:
            return None
        item.quantity = normalize_quantity(product, quantity)
        item.save(update_fields=("quantity", "updated_at"))
        return item


def transfer_item(*, buyer, source, destination, product, quantity):
    """Move stockless cart quantities while locking carts in a stable order."""
    if source.pk == destination.pk:
        raise ValidationError({"destination_cart": "Les paniers doivent être distincts."})
    with transaction.atomic():
        locked = list(Cart.objects.select_for_update().filter(pk__in=(source.pk, destination.pk)).order_by("pk"))
        source, destination = ({cart.pk: cart for cart in locked}[source.pk], {cart.pk: cart for cart in locked}[destination.pk])
        if source.buyer_id != buyer.id or destination.buyer_id != buyer.id:
            raise ValidationError({"destination_cart": "Les deux paniers doivent vous appartenir."})
        if source.business_id != destination.business_id:
            raise ValidationError({"destination_cart": "Les paniers doivent appartenir à la même entreprise."})
        require_mutable(source)
        require_mutable(destination)
        quantity = normalize_quantity(product, quantity)
        source_item = CartItem.objects.select_for_update().filter(cart=source, product=product).first()
        if not source_item:
            raise ValidationError({"product": "Le produit est absent du panier source."})
        if quantity > source_item.quantity:
            raise ValidationError({"quantity": "La quantité transférée dépasse la quantité disponible."})
        destination_item = CartItem.objects.select_for_update().filter(cart=destination, product=product).first()
        if destination_item:
            destination_item.quantity = normalize_quantity(product, destination_item.quantity + quantity)
            destination_item.save(update_fields=("quantity", "updated_at"))
        else:
            destination_item = CartItem.objects.create(cart=destination, product=product, quantity=quantity)
        if quantity == source_item.quantity:
            source_item.delete()
        else:
            source_item.quantity -= quantity
            source_item.save(update_fields=("quantity", "updated_at"))
        return destination_item
