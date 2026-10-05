"""Public representations of the global product taxonomy."""

from rest_framework import serializers

from .models import AttributeDefinition, ProductCategory
from .services import EffectiveAttribute


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

    def get_options(self, effective: EffectiveAttribute):
        options = [option for option in effective.definition.options.all() if option.is_active]
        return AttributeOptionSerializer(options, many=True).data
