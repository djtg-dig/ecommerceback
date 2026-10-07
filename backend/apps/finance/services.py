from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.choices import PaymentMethod

from apps.businesses.models import BusinessPaymentMethod
from apps.businesses.services import ensure_default_payment_methods

from .models import FinancialMovement, PaymentTransaction


EVENT_SOURCE = {
    FinancialMovement.EventType.SALE_PAYMENT: "sale",
    FinancialMovement.EventType.SALE_RETURN_REFUND: "sale_return",
    FinancialMovement.EventType.RECEIVABLE_PAYMENT: "receivable_payment",
    FinancialMovement.EventType.EXPENSE_PAYMENT: "expense_payment",
    FinancialMovement.EventType.SUPPLIER_PAYMENT: "supplier_payment",
}


def create_financial_movement(
    *, business, direction, amount, payment_method, event_type, created_by,
    sale=None, sale_return=None, receivable_payment=None, expense=None, expense_payment=None, supplier_payment=None, occurred_at=None, reason="",
    idempotency_key="", business_payment_method=None, transaction_reference="", recording_mode=PaymentTransaction.RecordingMode.MANUAL, recorded_by=None,
):
    """Append one source-backed ledger event, returning a prior idempotent event."""
    if direction not in FinancialMovement.Direction.values:
        raise ValidationError("Invalid financial movement.")
    ensure_default_payment_methods(business)
    if business_payment_method is None:
        if payment_method not in PaymentMethod.values:
            raise ValidationError("Invalid financial movement.")
        business_payment_method = BusinessPaymentMethod.objects.filter(
            business=business,
            category=payment_method,
            is_active=True,
        ).order_by("created_at").first()
    elif business_payment_method.business_id != business.id or not business_payment_method.is_active:
        raise ValidationError("Invalid business payment method.")
    if business_payment_method is None:
        raise ValidationError("No active payment method is available.")
    if recording_mode not in PaymentTransaction.RecordingMode.values:
        raise ValidationError("Invalid payment recording mode.")
    payment_method = business_payment_method.category
    occurred_at = parse_datetime(occurred_at) if isinstance(occurred_at, str) else (occurred_at or timezone.now())
    if occurred_at is None:
        raise ValidationError({"occurred_at": "Invalid occurred at."})
    if timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at, timezone.get_current_timezone())
    if occurred_at > timezone.now():
        raise ValidationError({"occurred_at": "Occurred at cannot be in the future."})
    if amount is None or amount <= 0:
        raise ValidationError({"amount": "Amount must be positive."})

    source_field = EVENT_SOURCE.get(event_type)
    source_values = {"sale": sale, "sale_return": sale_return, "receivable_payment": receivable_payment, "expense": expense, "expense_payment": expense_payment, "supplier_payment": supplier_payment}
    if source_field is None or [field for field, value in source_values.items() if value is not None] != [source_field]:
        raise ValidationError("The event type must match exactly one source.")
    source = source_values[source_field]
    source_business_id = source.expense.business_id if source_field == "expense_payment" else (source.purchase.business_id if source_field == "supplier_payment" else source.business_id)
    if source_business_id != business.id:
        raise ValidationError("The source must belong to the same Business.")

    with transaction.atomic():
        if idempotency_key:
            existing = FinancialMovement.objects.filter(
                business=business, idempotency_key=idempotency_key
            ).first()
            if existing:
                return existing
        payment_transaction = PaymentTransaction.objects.create(
            business=business,
            business_payment_method=business_payment_method,
            method_name_snapshot=business_payment_method.name,
            category_snapshot=business_payment_method.category,
            recording_mode=recording_mode,
            transaction_reference=transaction_reference,
            occurred_at=occurred_at,
            recorded_by=recorded_by or created_by,
        )
        return FinancialMovement.objects.create(
            business=business, direction=direction, amount=amount,
            currency=business.primary_currency, payment_method=payment_method,
            event_type=event_type, occurred_at=occurred_at,
            created_by=created_by, payment_transaction=payment_transaction, sale=sale, sale_return=sale_return, receivable_payment=receivable_payment,
            expense=expense, expense_payment=expense_payment, supplier_payment=supplier_payment, reason=reason, idempotency_key=idempotency_key,
        )


def reverse_movement(movement, *, created_by, reason, occurred_at=None):
    """Correct an expense payment with one opposite immutable ledger event."""
    if not reason or not reason.strip():
        raise ValidationError({"reason": "A reversal reason is required."})
    with transaction.atomic():
        original = FinancialMovement.objects.select_for_update().get(pk=movement.pk)
        if (
            original.event_type not in {FinancialMovement.EventType.EXPENSE_PAYMENT, FinancialMovement.EventType.SUPPLIER_PAYMENT}
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
            event_type=(FinancialMovement.EventType.EXPENSE_REVERSAL if original.event_type == FinancialMovement.EventType.EXPENSE_PAYMENT else FinancialMovement.EventType.SUPPLIER_PAYMENT_REVERSAL),
            occurred_at=occurred_at or timezone.now(), created_by=created_by,
            reason=reason.strip(), reversal_of=original,
        )


def financial_summary(queryset):
    """Aggregate the immutable ledger, including historical movements without traces."""
    totals = queryset.values("direction").annotate(total=Sum("amount"))
    values = {row["direction"]: row["total"] or Decimal("0") for row in totals}
    inflow = values.get(FinancialMovement.Direction.INFLOW, Decimal("0"))
    outflow = values.get(FinancialMovement.Direction.OUTFLOW, Decimal("0"))

    def groups(rows, key, defaults):
        data = {value: {key: value, "inflow": Decimal("0"), "outflow": Decimal("0"), "net": Decimal("0")} for value in defaults}
        for row in rows:
            value = row[key]
            entry = data.setdefault(value, {key: value, "inflow": Decimal("0"), "outflow": Decimal("0"), "net": Decimal("0")})
            entry["inflow" if row["direction"] == "INFLOW" else "outflow"] = row["total"] or Decimal("0")
        for entry in data.values(): entry["net"] = entry["inflow"] - entry["outflow"]
        return list(data.values())

    by_category = groups(queryset.values("payment_method", "direction").annotate(total=Sum("amount")), "payment_method", PaymentMethod.values)
    for row in by_category:
        row["category"] = row.pop("payment_method")
    mode_rows = []
    for row in queryset.values("payment_transaction__recording_mode", "direction").annotate(total=Sum("amount")):
        mode_rows.append({"mode": row["payment_transaction__recording_mode"] or "UNCLASSIFIED", "direction": row["direction"], "total": row["total"]})
    by_mode = groups(mode_rows, "mode", ("MANUAL", "AUTOMATIC", "UNCLASSIFIED"))
    methods = []
    for row in queryset.filter(payment_transaction__isnull=False).values("payment_transaction__business_payment_method__public_id", "payment_transaction__business_payment_method__name", "payment_transaction__method_name_snapshot", "payment_transaction__category_snapshot", "direction").annotate(total=Sum("amount")):
        key = row["payment_transaction__business_payment_method__public_id"]
        entry = next((x for x in methods if x["payment_method"] == key), None)
        if not entry:
            entry = {"payment_method": key, "current_name": row["payment_transaction__business_payment_method__name"], "category": row["payment_transaction__category_snapshot"], "snapshots": [], "inflow": Decimal("0"), "outflow": Decimal("0"), "net": Decimal("0")}; methods.append(entry)
        if row["payment_transaction__method_name_snapshot"] not in entry["snapshots"]: entry["snapshots"].append(row["payment_transaction__method_name_snapshot"])
        entry["inflow" if row["direction"] == "INFLOW" else "outflow"] += row["total"] or Decimal("0")
    for entry in methods: entry["net"] = entry["inflow"] - entry["outflow"]
    legacy_methods = [{"payment_method": row["category"], "total_inflow": row["inflow"], "total_outflow": row["outflow"], "net_flow": row["net"]} for row in by_category]
    return {"total_inflow": inflow, "total_outflow": outflow, "net_flow": inflow - outflow, "by_payment_method": legacy_methods, "by_category": by_category, "by_business_payment_method": methods, "by_recording_mode": by_mode}
