"""Serializers for public taxonomy metadata and tenant-scoped catalog items."""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Product, ProductCategory, ProductVariant
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

    def _resolved_category(self, product):
        cache_name = "_resolved_category_for_serialization"
        if not hasattr(product, cache_name):
            setattr(product, cache_name, resolve_product_category(product))
        return getattr(product, cache_name)

    def get_category(self, product):
        return self._resolved_category(product).code

    def get_category_name(self, product):
        return self._resolved_category(product).name

    def get_category_source(self, product):
        return self._resolved_category(product).source

    def get_product_type_key(self, product):
        return self._resolved_category(product).product_type_key

    class Meta:
        model = Product
        fields = (
            "public_id", "name", "description", "category", "category_code", "category_name",
            "category_source", "product_type_key",
            "internal_reference", "barcode", "selling_price", "cost_price", "currency", "attributes",
            "status", "created_at", "updated_at",
        )


class ProductWriteSerializer(serializers.ModelSerializer):
    """Validate writes using active leaf categories and their inherited schema."""

    category = serializers.SlugRelatedField(
        slug_field="code",
        queryset=ProductCategory.objects.all(),
        required=False,
        allow_null=True,
    )
    category_code = serializers.CharField(required=False, allow_null=True, allow_blank=False)
    currency = serializers.ChoiceField(choices=("CDF", "USD"), required=False)
    attributes = serializers.JSONField(required=False)

    class Meta:
        model = Product
        fields = (
            "name", "description", "category", "category_code", "internal_reference", "barcode", "selling_price",
            "cost_price", "currency", "attributes", "status",
        )
        extra_kwargs = {
            "description": {"required": False}, "internal_reference": {"required": False},
            "barcode": {"required": False}, "cost_price": {"required": False}, "status": {"required": False},
        }

    def validate(self, attrs):
        instance = self.instance
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
