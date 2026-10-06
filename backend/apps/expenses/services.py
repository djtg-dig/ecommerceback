from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

STANDARD = (
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
    from .models import ExpenseCategory

    for index, (code, name) in enumerate(STANDARD):
        ExpenseCategory.objects.get_or_create(
            business=business,
            code=code,
            defaults={"name": name, "is_system": True, "sort_order": index},
        )


def cancel_expense(expense, actor, reason):
    """Atomically transition one active expense to CANCELLED."""
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
