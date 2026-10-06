from django.contrib import admin

from .models import Expense, ExpenseCategory


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "business",
        "code",
        "name",
        "is_system",
        "is_active",
        "sort_order",
        "created_at",
    )
    list_filter = (
        "is_system",
        "is_active",
    )
    search_fields = (
        "public_id",
        "code",
        "name",
        "business__name",
    )
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "is_system",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj:
            readonly_fields.append("business")

        if obj and obj.is_system:
            readonly_fields.extend(
                (
                    "code",
                    "name",
                    "description",
                    "sort_order",
                )
            )

        return tuple(readonly_fields)

    def has_delete_permission(self, request, obj=None):
        """Preserve category history; deactivation is the supported lifecycle action."""
        return False


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "business",
        "category",
        "amount",
        "currency",
        "payment_method",
        "expense_date",
        "status",
        "created_by",
        "created_at",
    )
    list_filter = (
        "status",
        "currency",
        "payment_method",
        "expense_date",
        "category",
    )
    search_fields = (
        "public_id",
        "description",
        "reference",
        "business__name",
    )
    readonly_fields = (
        "public_id",
        "created_by",
        "created_at",
        "updated_at",
        "cancelled_by",
        "cancelled_at",
        "status",
        "cancellation_reason",
    )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))

        if obj:
            readonly_fields.append("business")

        if obj and obj.status == Expense.Status.CANCELLED:
            readonly_fields.extend(field.name for field in obj._meta.fields)

        return tuple(dict.fromkeys(readonly_fields))

    def has_delete_permission(self, request, obj=None):
        """Expenses are financial history and must never be physically deleted."""
        return False
