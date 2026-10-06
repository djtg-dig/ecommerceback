from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.common.choices import PaymentMethod

from .models import FinancialMovement


EVENT_SOURCE = {
    FinancialMovement.EventType.SALE_PAYMENT: "sale",
    FinancialMovement.EventType.RECEIVABLE_PAYMENT: "receivable_payment",
    FinancialMovement.EventType.EXPENSE_PAYMENT: "expense",
}


def create_financial_movement(
    *, business, direction, amount, payment_method, event_type, created_by,
    sale=None, receivable_payment=None, expense=None, occurred_at=None, reason="",
    idempotency_key="",
):
    """Append one source-backed ledger event, returning a prior idempotent event."""
    if direction not in FinancialMovement.Direction.values or payment_method not in PaymentMethod.values:
        raise ValidationError("Invalid financial movement.")
    if amount is None or amount <= 0:
        raise ValidationError({"amount": "Amount must be positive."})

    source_field = EVENT_SOURCE.get(event_type)
    source_values = {"sale": sale, "receivable_payment": receivable_payment, "expense": expense}
    if source_field is None or [field for field, value in source_values.items() if value is not None] != [source_field]:
        raise ValidationError("The event type must match exactly one source.")
    if source_values[source_field].business_id != business.id:
        raise ValidationError("The source must belong to the same Business.")

    with transaction.atomic():
        if idempotency_key:
            existing = FinancialMovement.objects.filter(
                business=business, idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing
        return FinancialMovement.objects.create(
            business=business, direction=direction, amount=amount,
            currency=business.primary_currency, payment_method=payment_method,
            event_type=event_type, occurred_at=occurred_at or timezone.now(),
            created_by=created_by, sale=sale, receivable_payment=receivable_payment,
            expense=expense, reason=reason, idempotency_key=idempotency_key,
        )


def reverse_movement(movement, *, created_by, reason, occurred_at=None):
    """Correct an expense payment with one opposite immutable ledger event."""
    if not reason or not reason.strip():
        raise ValidationError({"reason": "A reversal reason is required."})
    with transaction.atomic():
        original = FinancialMovement.objects.select_for_update().get(pk=movement.pk)
        if (
            original.event_type != FinancialMovement.EventType.EXPENSE_PAYMENT
            or original.reversal_of_id
            or hasattr(original, "reversal")
        ):
            raise ValidationError("This movement cannot be reversed.")
        direction = (
            FinancialMovement.Direction.OUTFLOW
            if original.direction == FinancialMovement.Direction.INFLOW
            else FinancialMovement.Direction.INFLOW
        )
        return FinancialMovement.objects.create(
            business=original.business, direction=direction, amount=original.amount,
            currency=original.currency, payment_method=original.payment_method,
            event_type=FinancialMovement.EventType.EXPENSE_REVERSAL,
            occurred_at=occurred_at or timezone.now(), created_by=created_by,
            reason=reason.strip(), reversal_of=original,
        )


def financial_summary(queryset):
    """Return informational inflow/outflow totals, including payment-method groups."""
    totals = queryset.values("direction").annotate(total=Sum("amount"))
    values = {row["direction"]: row["total"] or Decimal("0") for row in totals}
    inflow = values.get(FinancialMovement.Direction.INFLOW, Decimal("0"))
    outflow = values.get(FinancialMovement.Direction.OUTFLOW, Decimal("0"))

    grouped = {
        method: {
            "payment_method": method,
            "total_inflow": Decimal("0"),
            "total_outflow": Decimal("0"),
            "net_flow": Decimal("0"),
        }
        for method in PaymentMethod.values
    }
    for row in queryset.values("payment_method", "direction").annotate(total=Sum("amount")):
        entry = grouped[row["payment_method"]]
        key = "total_inflow" if row["direction"] == FinancialMovement.Direction.INFLOW else "total_outflow"
        entry[key] = row["total"] or Decimal("0")
    for entry in grouped.values():
        entry["net_flow"] = entry["total_inflow"] - entry["total_outflow"]

    return {
        "total_inflow": inflow,
        "total_outflow": outflow,
        "net_flow": inflow - outflow,
        "by_payment_method": list(grouped.values()),
    }
