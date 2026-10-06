import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.common.choices import PaymentMethod
from apps.finance.models import FinancialMovement
from apps.finance.services import create_financial_movement

from .models import Receivable, ReceivablePayment


class IdempotencyConflict(ValidationError):
    """A client reused an idempotency key with a different payment request."""


def payment_fingerprint(*, receivable, amount, payment_method, reference, notes):
    """Hash the immutable client intent used to safely recognize a retry."""
    payload = {
        "receivable": receivable.public_id,
        "amount": str(amount),
        "payment_method": payment_method,
        "reference": reference,
        "notes": notes,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def add_payment(
    receivable,
    actor,
    amount,
    payment_method,
    reference="",
    notes="",
    idempotency_key="",
):
    """Lock a receivable, append one payment and its Finance inflow atomically.

    An identical retry with an `Idempotency-Key` returns the original payment.
    Reusing that key for a different payload raises ``IdempotencyConflict``.
    """
    if amount is None or amount <= 0 or payment_method not in PaymentMethod.values:
        raise ValidationError("Invalid payment.")

    with transaction.atomic():
        receivable = Receivable.objects.select_for_update().get(pk=receivable.pk)
        fingerprint = payment_fingerprint(
            receivable=receivable,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
        )
        if idempotency_key:
            existing = ReceivablePayment.objects.filter(
                business=receivable.business,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                if existing.idempotency_fingerprint != fingerprint:
                    raise IdempotencyConflict("Idempotency key conflicts with a different payment.")
                return existing

        if receivable.status == Receivable.Status.PAID or amount > receivable.balance:
            raise ValidationError("Invalid payment.")

        payment = ReceivablePayment.objects.create(
            business=receivable.business,
            receivable=receivable,
            amount=amount,
            payment_method=payment_method,
            reference=reference,
            notes=notes,
            received_by=actor,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint if idempotency_key else "",
        )
        create_financial_movement(
            business=receivable.business,
            direction=FinancialMovement.Direction.INFLOW,
            amount=payment.amount,
            payment_method=payment.payment_method,
            event_type=FinancialMovement.EventType.RECEIVABLE_PAYMENT,
            created_by=actor,
            receivable_payment=payment,
            occurred_at=payment.paid_at,
        )
        balance = receivable.balance
        if balance == 0:
            receivable.status = Receivable.Status.PAID
            receivable.settled_at = timezone.now()
        else:
            receivable.status = Receivable.Status.PARTIALLY_PAID
        receivable.save(update_fields=("status", "settled_at", "updated_at"))
        return payment
