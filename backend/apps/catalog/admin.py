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
