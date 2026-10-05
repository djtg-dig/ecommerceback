"""Read services for resolving inherited catalog attributes."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError

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
