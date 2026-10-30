from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    product = serializers.CharField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit_code = serializers.CharField(source="product.unit_of_measure.code", read_only=True)
    unit = serializers.CharField(source="product.unit_of_measure.symbol", read_only=True)
    allows_decimal_quantity = serializers.BooleanField(source="product.unit_of_measure.allows_decimal_quantity", read_only=True)
    selling_price = serializers.DecimalField(source="product.selling_price", max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(source="product.currency", read_only=True)
    primary_image_url = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_primary_image_url(self, item):
        media = getattr(item.product, "_prefetched_objects_cache", {}).get("media")
        if media is None:
            media = item.product.media.all()
        image = next((entry for entry in media if entry.media_type == "IMAGE" and entry.is_primary), None)
        image = image or next((entry for entry in media if entry.media_type == "IMAGE"), None)
        return image.secure_url if image else None

    class Meta:
        model = CartItem
        fields = (
            "product", "product_name", "unit_code", "unit", "allows_decimal_quantity", "quantity", "selling_price", "currency",
            "primary_image_url", "created_at", "updated_at",
        )


class CartSerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    items = CartItemSerializer(many=True, read_only=True)

    class Meta:
        model = Cart
        fields = (
            "reference", "business", "business_name", "name", "status", "locked_at", "locked_by",
            "created_at", "updated_at", "items",
        )
        read_only_fields = ("reference", "status", "locked_at", "locked_by", "created_at", "updated_at", "items")

    def validate_name(self, value):
        normalized = " ".join(value.split())
        if not normalized:
            raise serializers.ValidationError("Le nom du panier ne peut pas être vide.")
        return normalized


class QuantitySerializer(serializers.Serializer):
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class AddProductSerializer(QuantitySerializer):
    product = serializers.CharField()


class AddToCartSerializer(AddProductSerializer):
    cart = serializers.CharField(required=False, allow_blank=False)


class TransferSerializer(AddProductSerializer):
    source_cart = serializers.CharField()
    destination_cart = serializers.CharField()
