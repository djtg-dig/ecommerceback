"""Read and validation services for the global taxonomy and business products."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import AttributeDefinition, ProductCategory


@dataclass(frozen=True)
class EffectiveAttribute:
    """An active attribute and the category from which it is inherited."""

    definition: AttributeDefinition
    inherited_from: ProductCategory


def category_lineage(category: ProductCategory) -> list[ProductCategory]:
    """Return categories from root to target and fail safely on invalid cycles."""
    lineage: list[ProductCategory] = []
    seen = set()
    current = category
    while current is not None:
        if current.pk in seen:
            raise ValidationError("La hiérarchie de catégorie contient un cycle.")
        seen.add(current.pk)
        lineage.append(current)
        current = current.parent
    return list(reversed(lineage))


def effective_attributes(category: ProductCategory) -> list[EffectiveAttribute]:
    """Resolve active attributes inherited from active ancestors, root first."""
    resolved: list[EffectiveAttribute] = []
    seen_codes: set[str] = set()
    for source in category_lineage(category):
        if not source.is_active:
            continue
        definitions = AttributeDefinition.objects.filter(category=source, is_active=True).prefetch_related("options")
        for definition in definitions:
            if definition.code not in seen_codes:
                resolved.append(EffectiveAttribute(definition=definition, inherited_from=source))
                seen_codes.add(definition.code)
    return resolved


def validate_leaf_category(category: ProductCategory) -> ProductCategory:
    """Ensure products use a live terminal taxonomy category."""
    if not category.is_active:
        raise ValidationError({"category": "La catégorie doit être active."})
    if category.children.exists():
        raise ValidationError({"category": "Un produit doit utiliser une catégorie feuille."})
    return category


def _invalid(message: str) -> ValidationError:
    return ValidationError({"attributes": message})


def _normalise_value(definition: AttributeDefinition, value):
    """Validate and convert one JSON value to a stable JSON-compatible value."""
    kind = definition.data_type
    if kind == AttributeDefinition.DataType.TEXT:
        if not isinstance(value, str):
            raise _invalid(f"{definition.code} doit être une chaîne.")
        return value
    if kind == AttributeDefinition.DataType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(f"{definition.code} doit être un entier.")
        return value
    if kind == AttributeDefinition.DataType.DECIMAL:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise _invalid(f"{definition.code} doit être un décimal.")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise _invalid(f"{definition.code} doit être un décimal valide.") from None
        if not decimal_value.is_finite():
            raise _invalid(f"{definition.code} doit être un décimal fini.")
        return format(decimal_value, "f")
    if kind == AttributeDefinition.DataType.BOOLEAN:
        if not isinstance(value, bool):
            raise _invalid(f"{definition.code} doit être booléen.")
        return value
    if kind == AttributeDefinition.DataType.DATE:
        if not isinstance(value, str):
            raise _invalid(f"{definition.code} doit être une date ISO-8601.")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise _invalid(f"{definition.code} doit être une date ISO-8601 valide.") from None
    if kind == AttributeDefinition.DataType.CHOICE:
        if not isinstance(value, str) or not definition.options.filter(value=value, is_active=True).exists():
            raise _invalid(f"{definition.code} doit être une option active.")
        return value
    raise _invalid(f"Type d'attribut inconnu pour {definition.code}.")


def validate_product_attributes(category: ProductCategory, attributes, *, variant_attributes: bool) -> dict:
    """Validate JSONB attributes against inherited definitions.

    Products carry only non-variant axes. Variants carry only variant axes and
    must include every required axis. The returned values are canonical JSON so
    a variant signature never depends on request key ordering or decimal syntax.
    """
    if not isinstance(attributes, dict):
        raise _invalid("Les attributs doivent être un objet JSON.")
    definitions = {item.definition.code: item.definition for item in effective_attributes(category)}
    expected = {
        code: definition
        for code, definition in definitions.items()
        if definition.is_variant_axis == variant_attributes
    }
    unknown = set(attributes) - set(expected)
    if unknown:
        raise _invalid(f"Attribut inconnu ou au mauvais niveau: {sorted(unknown)[0]}.")
    missing = [code for code, definition in expected.items() if definition.is_required and code not in attributes]
    if missing:
        raise _invalid(f"Attribut requis manquant: {sorted(missing)[0]}.")
    return {code: _normalise_value(expected[code], value) for code, value in attributes.items()}


def variant_attributes_signature(attributes: dict) -> str:
    """Hash canonical JSON values so equivalent variant combinations collide."""
    payload = json.dumps(attributes, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_business_sku_available(business, reference: str | None, *, product=None, variant=None) -> None:
    """Keep SKU values unique across products and variants of one business.

    PostgreSQL enforces per-table uniqueness; this cross-table check is the
    deliberate lightweight first version and is documented as not race-proof
    without a future central SKU table.
    """
    if not reference:
        return
    from .models import Product, ProductVariant

    products = Product.objects.filter(business=business, internal_reference=reference)
    if product is not None:
        products = products.exclude(pk=product.pk)
    variants = ProductVariant.objects.filter(product__business=business, internal_reference=reference)
    if variant is not None:
        variants = variants.exclude(pk=variant.pk)
    if products.exists() or variants.exists():
        raise ValidationError({"internal_reference": "Cette référence interne existe déjà pour ce commerce."})


def create_product(*, business, values: dict):
    """Create a product with bounded public-ID collision retries."""
    from apps.businesses.identifiers import generate_product_public_id
    from .models import Product

    for _ in range(5):
        values["public_id"] = generate_product_public_id()
        try:
            with transaction.atomic():
                return Product.objects.create(business=business, **values)
        except IntegrityError as exc:
            if "public_id" not in str(exc):
                raise
    raise RuntimeError("Impossible de générer un identifiant public produit unique.")


def create_variant(*, product, values: dict):
    """Create a variant with bounded public-ID collision retries."""
    from apps.businesses.identifiers import generate_product_variant_public_id
    from .models import ProductVariant

    for _ in range(5):
        values["public_id"] = generate_product_variant_public_id()
        try:
            with transaction.atomic():
                return ProductVariant.objects.create(product=product, **values)
        except IntegrityError as exc:
            if "public_id" not in str(exc):
                raise
    raise RuntimeError("Impossible de générer un identifiant public variante unique.")
