"""Read-oriented inventory administration that preserves movement history."""

from django.contrib import admin

from .models import InventoryItem, StockMovement


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("public_id", "business", "product", "variant", "quantity", "reserved_quantity", "low_stock_threshold")
    list_filter = ("business",)
    search_fields = ("public_id", "product__public_id", "variant__public_id")
    readonly_fields = ("id", "public_id", "quantity", "reserved_quantity", "created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("public_id", "inventory_item", "movement_type", "quantity", "quantity_before", "quantity_after", "performed_by", "created_at")
    list_filter = ("movement_type", "business")
    search_fields = ("public_id", "inventory_item__public_id", "reason")
    readonly_fields = tuple(field.name for field in StockMovement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
