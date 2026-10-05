"""Diagnostic administration for the global taxonomy."""

from django.contrib import admin

from .models import AttributeDefinition, AttributeOption, ProductCategory


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "level", "product_type_key", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "slug")
    readonly_fields = ("id", "level", "created_at", "updated_at")


@admin.register(AttributeDefinition)
class AttributeDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "data_type", "is_active", "sort_order")
    list_filter = ("data_type", "is_active", "is_filterable", "is_variant_axis")
    search_fields = ("code", "name", "category__code")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AttributeOption)
class AttributeOptionAdmin(admin.ModelAdmin):
    list_display = ("value", "label", "attribute_definition", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("value", "label", "attribute_definition__code")
    readonly_fields = ("id", "created_at", "updated_at")

from .models import Product, ProductVariant


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Read-oriented management of tenant products without exposing UUIDs."""

    list_display = ("public_id", "name", "business", "category", "selling_price", "currency", "status")
    list_filter = ("status", "currency", "category")
    search_fields = ("public_id", "name", "internal_reference", "barcode")
    readonly_fields = ("id", "public_id", "created_at", "updated_at")


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """Inspect variants and their stable combination signatures."""

    list_display = ("public_id", "product", "internal_reference", "selling_price", "status")
    list_filter = ("status",)
    search_fields = ("public_id", "internal_reference", "barcode", "product__name")
    readonly_fields = ("id", "public_id", "variant_signature", "created_at", "updated_at")
