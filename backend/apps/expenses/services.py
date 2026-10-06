"""Business services that own the Expenses domain's state transitions and seed data."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

STANDARD_EXPENSE_CATEGORIES = (
    ("RENT", "Loyer"),
    ("ELECTRICITY", "Électricité"),
    ("WATER", "Eau"),
    ("INTERNET", "Internet"),
    ("TRANSPORT", "Transport"),
    ("SALARY", "Salaire"),
    ("MAINTENANCE", "Maintenance"),
    ("SUPPLIES", "Fournitures"),
    ("TAX", "Taxe / impôt"),
    ("MARKETING", "Marketing"),
    ("OTHER", "Autre"),
)


def ensure_default_expense_categories(business):
    """
    Ensure a Business owns every standard expense category exactly once.

    The `(business, code)` uniqueness invariant makes repeated calls safe. If a
    pre-existing custom category uses a reserved standard code, it is deliberately
    preserved: initialization never overwrites user-entered names or settings.
    """
    from .models import ExpenseCategory

    for sort_order, (code, name) in enumerate(STANDARD_EXPENSE_CATEGORIES):
        ExpenseCategory.objects.get_or_create(
            business=business,
            code=code,
            defaults={
                "name": name,
                "is_system": True,
                "is_active": True,
                "sort_order": sort_order,
            },
        )


def cancel_expense(expense, actor, reason):
    """
    Cancel an active expense without deleting its history.

    The row lock prevents two concurrent cancellation requests from both succeeding.
    CANCELLED is terminal, so the caller receives a validation failure after any
    earlier cancellation has committed.
    """
    from .models import Expense

    with transaction.atomic():
        locked_expense = Expense.objects.select_for_update().get(pk=expense.pk)
        if locked_expense.status != Expense.Status.ACTIVE:
            raise ValidationError("Only active expenses can be cancelled.")

        locked_expense.status = Expense.Status.CANCELLED
        locked_expense.cancelled_by = actor
        locked_expense.cancelled_at = timezone.now()
        locked_expense.cancellation_reason = reason
        locked_expense.save(
            update_fields=(
                "status",
                "cancelled_by",
                "cancelled_at",
                "cancellation_reason",
                "updated_at",
            )
        )

    return locked_expense
