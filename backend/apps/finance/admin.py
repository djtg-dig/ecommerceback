from django.contrib import admin

from .models import FinancialMovement


@admin.register(FinancialMovement)
class FinancialMovementAdmin(admin.ModelAdmin):
    list_display = (
        "public_id", "business", "direction", "amount", "currency",
        "payment_method", "event_type", "occurred_at", "created_by", "created_at",
    )
    readonly_fields = tuple(field.name for field in FinancialMovement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
