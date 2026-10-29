from decimal import Decimal

from rest_framework import serializers

from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    product = serializers.CharField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.CharField(source="product.unit_of_measure.symbol", read_only=True)

    class Meta:
        model = CartItem
        fields = ("product", "product_name", "unit", "quantity", "created_at", "updated_at")


class CartSerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    items = CartItemSerializer(many=True, read_only=True)

    class Meta:
        model = Cart
        fields = (
            "reference", "business", "name", "status", "locked_at", "locked_by",
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
