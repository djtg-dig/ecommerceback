"""Read and write serializers that prevent direct balance manipulation."""

from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Product, ProductVariant
from .models import InventoryItem, StockMovement


class InventoryItemSerializer(serializers.ModelSerializer):
    """Safe inventory representation using public identifiers only."""

    product = serializers.CharField(source="product.public_id", read_only=True, allow_null=True)
    variant = serializers.CharField(source="variant.public_id", read_only=True, allow_null=True)
    available_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    item_name = serializers.SerializerMethodField()
    internal_reference = serializers.SerializerMethodField()
    stock_status = serializers.SerializerMethodField()
    last_movement_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = InventoryItem
        fields = ("public_id", "product", "variant", "item_name", "internal_reference", "quantity", "reserved_quantity", "available_quantity", "low_stock_threshold", "is_low_stock", "stock_status", "last_movement_at", "created_at", "updated_at")

    def get_item_name(self, item):
        return item.product.name if item.product_id else item.variant.product.name

    def get_internal_reference(self, item):
        target = item.product if item.product_id else item.variant
        return target.internal_reference

    def get_stock_status(self, item):
        if item.available_quantity == 0:
            return "OUT_OF_STOCK"
        if item.is_low_stock:
            return "LOW_STOCK"
        return "AVAILABLE"


class InventoryItemCreateSerializer(serializers.Serializer):
    """Accept one sellable public identifier; initial balance is always zero."""

    product = serializers.SlugRelatedField(slug_field="public_id", queryset=Product.objects.all(), required=False)
    variant = serializers.SlugRelatedField(slug_field="public_id", queryset=ProductVariant.objects.select_related("product").all(), required=False)
    low_stock_threshold = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, allow_null=True, min_value=0)

    def validate(self, attrs):
        if bool(attrs.get("product")) == bool(attrs.get("variant")):
            raise serializers.ValidationError("Choisir exactement product ou variant.")
        return attrs


class StockMovementSerializer(serializers.ModelSerializer):
    """Expose immutable event data without internal relationships."""

    performed_by = serializers.UUIDField(source="performed_by_id", read_only=True)
    inventory_item = serializers.CharField(source="inventory_item.public_id", read_only=True)
    item_name = serializers.SerializerMethodField()
    product = serializers.SerializerMethodField()
    variant = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = ("public_id", "inventory_item", "item_name", "product", "variant", "movement_type", "quantity", "quantity_before", "quantity_after", "reason", "reference_type", "reference_id", "performed_by", "created_at")

    def get_item_name(self, movement):
        item = movement.inventory_item
        return item.product.name if item.product_id else item.variant.product.name

    def get_product(self, movement):
        item = movement.inventory_item
        return item.product.public_id if item.product_id else item.variant.product.public_id

    def get_variant(self, movement):
        item = movement.inventory_item
        return item.variant.public_id if item.variant_id else None


class StockMovementCreateSerializer(serializers.Serializer):
    """Separate client inputs for IN/OUT and absolute adjustment targets."""

    type = serializers.ChoiceField(choices=("IN", "OUT", "ADJUSTMENT"))
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, min_value=Decimal("0.001"))
    target_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False, min_value=0)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, attrs):
        from decimal import Decimal
        if attrs["type"] == "ADJUSTMENT":
            if "target_quantity" not in attrs or "quantity" in attrs:
                raise serializers.ValidationError("ADJUSTMENT exige target_quantity uniquement.")
        elif "quantity" not in attrs or "target_quantity" in attrs:
            raise serializers.ValidationError("IN et OUT exigent quantity uniquement.")
        return attrs
