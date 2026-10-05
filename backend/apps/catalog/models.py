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


class Product(models.Model):
    """A business-owned catalog item; it deliberately contains no stock balance."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="products")
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    internal_reference = models.CharField(max_length=100, null=True, blank=True)
    barcode = models.CharField(max_length=128, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=14, decimal_places=2)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, choices=(("CDF", "CDF"), ("USD", "USD")))
    attributes = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "public_id")
        constraints = [
            models.UniqueConstraint(
                fields=("business", "internal_reference"),
                condition=models.Q(internal_reference__isnull=False),
                name="catalog_product_business_internal_reference_unique",
            ),
            models.CheckConstraint(condition=models.Q(selling_price__gte=0), name="catalog_product_selling_price_nonnegative"),
            models.CheckConstraint(
                condition=models.Q(cost_price__isnull=True) | models.Q(cost_price__gte=0),
                name="catalog_product_cost_price_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def product_type_key(self):
        """Expose the category-derived type without duplicating it in this table."""
        return self.category.product_type_key

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_product_public_id

        if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists():
            raise ValidationError({"public_id": "L'identifiant public produit est immuable."})
        if not self.public_id:
            self.public_id = generate_product_public_id()
        if self.internal_reference == "":
            self.internal_reference = None
        if self.barcode == "":
            self.barcode = None
        if not self.currency and self.business_id:
            self.currency = self.business.primary_currency
        return super().save(*args, **kwargs)


class ProductVariant(models.Model):
    """A sellable option combination whose prices optionally override its product."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    internal_reference = models.CharField(max_length=100, null=True, blank=True)
    barcode = models.CharField(max_length=128, null=True, blank=True)
    attributes = models.JSONField(default=dict)
    variant_signature = models.CharField(max_length=64, editable=False)
    selling_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    cost_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("public_id",)
        constraints = [
            models.UniqueConstraint(fields=("product", "variant_signature"), name="catalog_variant_product_signature_unique"),
            models.UniqueConstraint(
                fields=("product", "internal_reference"),
                condition=models.Q(internal_reference__isnull=False),
                name="catalog_variant_product_internal_reference_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(selling_price__isnull=True) | models.Q(selling_price__gte=0),
                name="catalog_variant_selling_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(cost_price__isnull=True) | models.Q(cost_price__gte=0),
                name="catalog_variant_cost_price_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return self.public_id

    @property
    def effective_selling_price(self):
        """Use the product price unless the variant explicitly overrides it."""
        return self.selling_price if self.selling_price is not None else self.product.selling_price

    @property
    def effective_cost_price(self):
        """Use the product cost unless the variant explicitly overrides it."""
        return self.cost_price if self.cost_price is not None else self.product.cost_price

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_product_variant_public_id
        from .services import variant_attributes_signature

        if self.pk and type(self).objects.filter(pk=self.pk).exclude(public_id=self.public_id).exists():
            raise ValidationError({"public_id": "L'identifiant public variante est immuable."})
        if not self.public_id:
            self.public_id = generate_product_variant_public_id()
        if self.internal_reference == "":
            self.internal_reference = None
        if self.barcode == "":
            self.barcode = None
        self.variant_signature = variant_attributes_signature(self.attributes)
        return super().save(*args, **kwargs)
