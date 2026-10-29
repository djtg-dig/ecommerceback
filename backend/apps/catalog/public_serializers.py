"""Strictly public catalogue projections, deliberately separate from back-office serializers."""

from rest_framework import serializers

from .models import Product, ProductCategory


class PublicProductSerializer(serializers.ModelSerializer):
    business = serializers.CharField(source="business.public_id", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    category = serializers.CharField(source="category.slug", read_only=True, allow_null=True)
    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    unit = serializers.CharField(source="unit_of_measure.symbol", read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ("public_id", "name", "description", "business", "business_name", "category", "category_name", "selling_price", "min_price", "max_price", "currency", "is_negotiable", "unit", "image")

    def get_image(self, product):
        media = getattr(product, "public_images", ())
        image = next((item for item in media if item.is_primary), None) or next(iter(media), None)
        return image.secure_url if image else None


class PublicCategorySerializer(serializers.ModelSerializer):
    parent = serializers.CharField(source="parent.slug", read_only=True, allow_null=True)

    class Meta:
        model = ProductCategory
        fields = ("slug", "name", "description", "parent")
