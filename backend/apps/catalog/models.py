"""Models for the global product taxonomy and its reusable attributes."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class ProductCategory(models.Model):
    """A global category, organised as a tree with at most three levels."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    product_type_key = models.CharField(max_length=64, null=True, blank=True, unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name", "code")

    def __str__(self) -> str:
        return self.name

    @property
    def level(self) -> int:
        """Return the one-based level, while detecting corrupted parent chains."""
        current = self
        seen: set[uuid.UUID] = set()
        depth = 0
        while current is not None:
            if current.pk in seen:
                raise ValidationError({"parent": "La hiérarchie contient un cycle."})
            seen.add(current.pk)
            depth += 1
            current = current.parent
        return depth

    def clean(self) -> None:
        """Reject self references, cycles and a fourth hierarchy level."""
        super().clean()
        if self.product_type_key == "":
            self.product_type_key = None
        if self.parent_id is None:
            return
        if self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "Une catégorie ne peut pas être son propre parent."})

        current = self.parent
        seen: set[uuid.UUID] = {self.pk} if self.pk else set()
        ancestor_count = 0
        while current is not None:
            if current.pk in seen:
                raise ValidationError({"parent": "Une catégorie ne peut pas créer un cycle."})
            seen.add(current.pk)
            ancestor_count += 1
            if ancestor_count >= 3:
                raise ValidationError({"parent": "La hiérarchie est limitée à trois niveaux."})
            current = current.parent

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.full_clean()
        return super().save(*args, **kwargs)


class AttributeDefinition(models.Model):
    """A reusable product field attached to one taxonomy category."""

    class DataType(models.TextChoices):
        TEXT = "text", "Texte"
        INTEGER = "integer", "Entier"
        DECIMAL = "decimal", "Décimal"
        BOOLEAN = "boolean", "Booléen"
        CHOICE = "choice", "Choix"
        DATE = "date", "Date"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="attributes")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=160)
    data_type = models.CharField(max_length=16, choices=DataType.choices)
    unit = models.CharField(max_length=32, blank=True)
    is_required = models.BooleanField(default=False)
    is_filterable = models.BooleanField(default=False)
    is_variant_axis = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("category", "code"), name="catalog_attribute_category_code_unique")]
        ordering = ("sort_order", "code")

    def __str__(self) -> str:
        return f"{self.category.code}: {self.code}"

    def clean(self) -> None:
        """Do not permit a child to shadow an inherited attribute code."""
        super().clean()
        if not self.category_id or not self.code:
            return
        ancestor = self.category.parent
        seen: set[uuid.UUID] = set()
        while ancestor is not None:
            if ancestor.pk in seen:
                raise ValidationError({"category": "La hiérarchie de catégorie contient un cycle."})
            seen.add(ancestor.pk)
            if AttributeDefinition.objects.filter(category=ancestor, code=self.code).exclude(pk=self.pk).exists():
                raise ValidationError({"code": "Ce code est déjà défini par une catégorie ancêtre."})
            ancestor = ancestor.parent

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class AttributeOption(models.Model):
    """An allowed value for an attribute whose type is ``choice``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attribute_definition = models.ForeignKey(
        AttributeDefinition, on_delete=models.PROTECT, related_name="options"
    )
    value = models.CharField(max_length=128)
    label = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("attribute_definition", "value"), name="catalog_option_definition_value_unique")]
        ordering = ("sort_order", "label", "value")

    def __str__(self) -> str:
        return self.label
