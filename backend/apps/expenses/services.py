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
        if locked_expense.payments.filter(reversed_at__isnull=True).exists():
            raise ValidationError("Expense payments must be reversed before cancellation.")

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


def update_expense(expense, changes):
    """Update an active Expense while serializing changes with its payments.

    Expense payments lock the same parent row before checking the remaining
    balance. Sharing that lock guarantees that a concurrent amount reduction
    and payment cannot both validate against stale values.
    """
    from .models import Expense

    with transaction.atomic():
        locked_expense = Expense.objects.select_for_update().get(pk=expense.pk)
        if locked_expense.status != Expense.Status.ACTIVE:
            raise ValidationError("Cancelled expenses are immutable.")

        for field, value in changes.items():
            setattr(locked_expense, field, value)

        locked_expense.save()

    return locked_expense

import hashlib
import json

from apps.common.choices import PaymentMethod
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement, reverse_movement


class ExpensePaymentIdempotencyConflict(ValidationError):
    """An idempotency key was reused with a different Expense payment intent."""


def expense_payment_fingerprint(*, expense, amount, payment_method):
    """Bind a retry key to the exact expense and monetary payload."""
    payload = {
        "expense": expense.public_id,
        "amount": str(amount),
        "payment_method": payment_method,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def add_expense_payment(expense, actor, amount, payment_method, idempotency_key=""):
    """Lock an Expense and append its real outflow in the same transaction."""
    from .models import Expense, ExpensePayment

    if amount is None or amount <= 0 or payment_method not in PaymentMethod.values:
        raise ValidationError("Invalid expense payment.")
    with transaction.atomic():
        locked_expense = Expense.objects.select_for_update().get(pk=expense.pk)
        if locked_expense.status != Expense.Status.ACTIVE:
            raise ValidationError("Only active expenses can be paid.")
        fingerprint = expense_payment_fingerprint(
            expense=locked_expense,
            amount=amount,
            payment_method=payment_method,
        )
        if idempotency_key:
            existing = ExpensePayment.objects.filter(
                expense=locked_expense,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                if existing.idempotency_fingerprint != fingerprint:
                    raise ExpensePaymentIdempotencyConflict("Idempotency key conflicts with a different payment.")
                return existing
        if amount > locked_expense.balance:
            raise ValidationError("Payment exceeds the remaining expense balance.")
        payment = ExpensePayment.objects.create(
            expense=locked_expense,
            amount=amount,
            payment_method=payment_method,
            created_by=actor,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else "",
        )
        create_financial_movement(
            business=locked_expense.business,
            direction=FinancialMovement.Direction.OUTFLOW,
            amount=payment.amount,
            payment_method=payment.payment_method,
            event_type=FinancialMovement.EventType.EXPENSE_PAYMENT,
            created_by=actor,
            expense_payment=payment,
            occurred_at=payment.paid_at,
        )
        return payment


def reverse_expense_payment(payment, actor, reason):
    """Reverse one Expense payment without deleting historical payment evidence."""
    from .models import ExpensePayment

    if not reason or not reason.strip():
        raise ValidationError({"reason": "A reversal reason is required."})
    with transaction.atomic():
        locked_payment = ExpensePayment.objects.select_for_update().select_related("expense").get(pk=payment.pk)
        if locked_payment.is_reversed:
            raise ValidationError("This expense payment has already been reversed.")
        movement = FinancialMovement.objects.select_for_update().get(expense_payment=locked_payment)
        reverse_movement(movement, created_by=actor, reason=reason)
        locked_payment.reversed_at = timezone.now()
        locked_payment.reversed_by = actor
        locked_payment.reversal_reason = reason.strip()
        locked_payment.save(update_fields=("reversed_at", "reversed_by", "reversal_reason"))
        return locked_payment
