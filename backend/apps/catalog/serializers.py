"""Serializers for public taxonomy metadata and tenant-scoped catalog items."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Product, ProductCategory, ProductVariant, UnitOfMeasure
from .registry import get_category as get_registry_category
from .registry import validate_attributes as validate_registry_attributes
from .services import ensure_business_sku_available, validate_leaf_category, validate_product_attributes
from .services import resolve_product_category


class ProductCategorySerializer(serializers.ModelSerializer):
    """A flat category record clients can use to reconstruct the tree."""

    parent_code = serializers.CharField(source="parent.code", read_only=True, allow_null=True)
    level = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProductCategory
        fields = ("code", "name", "slug", "description", "parent_code", "level", "product_type_key", "sort_order")


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    """Référence publique et immuable des unités de mesure."""

    class Meta:
        model = UnitOfMeasure
        fields = ("code", "name", "symbol", "category", "allows_decimal_quantity")


class AttributeOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    sort_order = serializers.IntegerField()


class EffectiveAttributeSerializer(serializers.Serializer):
    """An attribute definition accompanied by its source category code."""

    code = serializers.CharField(source="definition.code")
    name = serializers.CharField(source="definition.name")
    data_type = serializers.CharField(source="definition.data_type")
    unit = serializers.CharField(source="definition.unit")
    is_required = serializers.BooleanField(source="definition.is_required")
    is_filterable = serializers.BooleanField(source="definition.is_filterable")
    is_variant_axis = serializers.BooleanField(source="definition.is_variant_axis")
    sort_order = serializers.IntegerField(source="definition.sort_order")
    inherited_from = serializers.CharField(source="inherited_from.code")
    options = serializers.SerializerMethodField()

    @extend_schema_field(AttributeOptionSerializer(many=True))
    def get_options(self, effective):
        options = [option for option in effective.definition.options.all() if option.is_active]
        return AttributeOptionSerializer(options, many=True).data


class ProductOutputSerializer(serializers.ModelSerializer):
    """Safe product representation that exposes category codes, never UUIDs."""

    category = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    category_source = serializers.SerializerMethodField()
    product_type_key = serializers.SerializerMethodField()
    primary_image_url = serializers.SerializerMethodField()
    unit_of_measure = serializers.SlugRelatedField(slug_field="code", read_only=True)
    unit_symbol = serializers.CharField(source="unit_of_measure.symbol", read_only=True)

    def _resolved_category(self, product):
        cache_name = "_resolved_category_for_serialization"
        if not hasattr(product, cache_name):
            setattr(product, cache_name, resolve_product_category(product))
        return getattr(product, cache_name)

    @extend_schema_field(serializers.CharField())
    def get_category(self, product):
        return self._resolved_category(product).code

    @extend_schema_field(serializers.CharField())
    def get_category_name(self, product):
        return self._resolved_category(product).name

    @extend_schema_field(serializers.CharField())
    def get_category_source(self, product):
        return self._resolved_category(product).source

    @extend_schema_field(serializers.CharField())
    def get_product_type_key(self, product):
        return self._resolved_category(product).product_type_key

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_primary_image_url(self, product):
        prefetched = getattr(product, "_prefetched_objects_cache", {}).get("media")
        if prefetched is not None:
            primary = next((item for item in prefetched if item.is_primary), None)
            return (primary or next(iter(prefetched), None)).secure_url if prefetched else None
        item = product.media.filter(media_type="IMAGE").only("secure_url").order_by("-is_primary", "position", "created_at", "id").first()
        return item.secure_url if item else None

    class Meta:
        model = Product
        fields = (
            "public_id", "name", "description", "category", "category_code", "category_name",
            "category_source", "product_type_key",
            "internal_reference", "barcode", "unit_of_measure", "unit_symbol", "selling_price", "min_price", "max_price", "is_negotiable", "cost_price", "currency", "attributes",
            "status", "is_public", "primary_image_url", "created_at", "updated_at",
        )


class ProductPageSerializer(serializers.Serializer):
    """Contrat paginé de la collection de produits d'une entreprise."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ProductOutputSerializer(many=True)


class ProductWriteSerializer(serializers.ModelSerializer):
    """Validate writes using active leaf categories and their inherited schema."""

    category = serializers.SlugRelatedField(
        slug_field="code",
        queryset=ProductCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    category_code = serializers.CharField(required=False, allow_null=True, allow_blank=False)
    # Currency is business-owned. The legacy field remains output-only so old
    # products retain their historic code without accepting client overrides.
    currency = serializers.CharField(read_only=True)
    min_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    max_price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    attributes = serializers.JSONField(required=False)
    unit_of_measure = serializers.SlugRelatedField(slug_field="code", queryset=UnitOfMeasure.objects.all(), required=False)

    class Meta:
        model = Product
        fields = (
            "name", "description", "category", "category_code", "internal_reference", "barcode", "unit_of_measure", "selling_price",
            "cost_price", "min_price", "max_price", "is_negotiable", "currency", "attributes", "status", "is_public",
        )
        extra_kwargs = {
            "description": {"required": False}, "internal_reference": {"required": False},
            "barcode": {"required": False}, "cost_price": {"required": False}, "status": {"required": False},
            "selling_price": {"required": False},
        }

    def validate(self, attrs):
        instance = self.instance
        # A legacy client can still send selling_price while deployments roll out.
        legacy_price = attrs.get("selling_price")
        if legacy_price is not None and "min_price" not in attrs and "max_price" not in attrs:
            attrs["min_price"] = legacy_price
            attrs["max_price"] = legacy_price
        if not instance and ("min_price" not in attrs or "max_price" not in attrs):
            raise serializers.ValidationError({"min_price": "Indiquez les prix minimum et maximum."})
        minimum = attrs.get("min_price", instance.min_price if instance else None)
        maximum = attrs.get("max_price", instance.max_price if instance else None)
        if minimum is not None and maximum is not None and maximum < minimum:
            raise serializers.ValidationError({"max_price": "Le prix maximum doit être supérieur ou égal au prix minimum."})
        if maximum is not None:
            attrs["selling_price"] = maximum
        category_supplied = "category" in attrs
        registry_supplied = "category_code" in attrs
        category = attrs.get("category", instance.category if instance else None)
        category_code = attrs.get("category_code", instance.category_code if instance else None)
        if category_supplied and registry_supplied and category is not None and category_code:
            raise serializers.ValidationError(
                {"category": "Indiquez une seule source de catégorie."}
            )
        if category_supplied and category is not None:
            category_code = None
            attrs["category_code"] = None
        elif registry_supplied and category_code:
            category = None
            attrs["category"] = None
        attributes = attrs.get("attributes", instance.attributes if instance else {})
        try:
            for field in ("selling_price", "cost_price"):
                value = attrs.get(field)
                if value is not None and value < 0:
                    raise serializers.ValidationError({field: "Le prix ne peut pas être négatif."})
            if bool(category) == bool(category_code):
                raise DjangoValidationError(
                    {"category": "Indiquez exactement une catégorie historique ou category_code."}
                )
            if category is not None:
                validate_leaf_category(category)
                attrs["attributes"] = validate_product_attributes(
                    category,
                    attributes,
                    variant_attributes=False,
                )
            else:
                if get_registry_category(category_code) is None:
                    raise DjangoValidationError({"category_code": "Catégorie Python inconnue."})
                attrs["attributes"] = validate_registry_attributes(
                    category_code,
                    attributes,
                    variant=False,
                )
            source_changed = instance and (
                category != instance.category or category_code != instance.category_code
            )
            if source_changed:
                for variant in instance.variants.all():
                    if category is not None:
                        validate_product_attributes(category, variant.attributes, variant_attributes=True)
                    else:
                        validate_registry_attributes(category_code, variant.attributes, variant=True)
            business = self.context["business"]
            ensure_business_sku_available(business, attrs.get("internal_reference", instance.internal_reference if instance else None), product=instance)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}) from exc
        return attrs


class ProductVariantOutputSerializer(serializers.ModelSerializer):
    """Safe variant output with resolved effective prices."""

    effective_selling_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    effective_cost_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = ProductVariant
        fields = (
            "public_id", "internal_reference", "barcode", "attributes", "selling_price", "cost_price",
            "effective_selling_price", "effective_cost_price", "status", "created_at", "updated_at",
        )


class ProductVariantWriteSerializer(serializers.ModelSerializer):
    """Validate only category variant axes and reject duplicate business SKUs."""

    attributes = serializers.JSONField(required=False)

    class Meta:
        model = ProductVariant
        fields = ("internal_reference", "barcode", "attributes", "selling_price", "cost_price", "status")
        extra_kwargs = {
            "internal_reference": {"required": False}, "barcode": {"required": False},
            "selling_price": {"required": False}, "cost_price": {"required": False}, "status": {"required": False},
        }

    def validate(self, attrs):
        product = self.context["product"]
        instance = self.instance
        attributes = attrs.get("attributes", instance.attributes if instance else {})
        try:
            for field in ("selling_price", "cost_price"):
                value = attrs.get(field)
                if value is not None and value < 0:
                    raise serializers.ValidationError({field: "Le prix ne peut pas être négatif."})
            if product.category_id is not None:
                attrs["attributes"] = validate_product_attributes(
                    product.category,
                    attributes,
                    variant_attributes=True,
                )
            else:
                attrs["attributes"] = validate_registry_attributes(
                    product.category_code,
                    attributes,
                    variant=True,
                )
            ensure_business_sku_available(
                product.business,
                attrs.get("internal_reference", instance.internal_reference if instance else None),
                variant=instance,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}) from exc
        return attrs


class PosSearchResultSerializer(serializers.Serializer):
    """Compact sellable projection consumed by the mobile POS."""

    type = serializers.ChoiceField(choices=("PRODUCT", "VARIANT"))
    public_id = serializers.CharField()
    product_public_id = serializers.CharField()
    name = serializers.CharField()
    variant_label = serializers.CharField(allow_null=True)
    internal_reference = serializers.CharField(allow_null=True)
    barcode = serializers.CharField(allow_null=True)
    effective_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.ChoiceField(choices=("CDF", "USD"))
    available_quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit_code = serializers.CharField()
    unit_symbol = serializers.CharField()
    allows_decimal_quantity = serializers.BooleanField()
