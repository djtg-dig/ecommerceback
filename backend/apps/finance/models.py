import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.choices import PaymentMethod

from .identifiers import generate_financial_movement_public_id


class FinancialMovement(models.Model):
    """An append-only financial event belonging to one Business."""

    class Direction(models.TextChoices):
        INFLOW = "INFLOW", "Inflow"
        OUTFLOW = "OUTFLOW", "Outflow"

    class EventType(models.TextChoices):
        SALE_PAYMENT = "SALE_PAYMENT", "Sale payment"
        RECEIVABLE_PAYMENT = "RECEIVABLE_PAYMENT", "Receivable payment"
        EXPENSE_PAYMENT = "EXPENSE_PAYMENT", "Expense payment"
        EXPENSE_REVERSAL = "EXPENSE_REVERSAL", "Expense reversal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, choices=(("CDF", "CDF"), ("USD", "USD")))
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    occurred_at = models.DateTimeField()
    created_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT)
    reason = models.CharField(max_length=500, blank=True)
    sale = models.ForeignKey("sales.Sale", null=True, blank=True, on_delete=models.PROTECT)
    receivable_payment = models.OneToOneField(
        "receivables.ReceivablePayment", null=True, blank=True, on_delete=models.PROTECT
    )
    expense = models.ForeignKey("expenses.Expense", null=True, blank=True, on_delete=models.PROTECT)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )
    idempotency_key = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at", "-created_at")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="financial_movement_amount_positive"),
            models.CheckConstraint(
                condition=(
                    Q(reversal_of__isnull=False, sale__isnull=True, receivable_payment__isnull=True, expense__isnull=True)
                    | Q(reversal_of__isnull=True)
                    & (
                        Q(sale__isnull=False, receivable_payment__isnull=True, expense__isnull=True)
                        | Q(sale__isnull=True, receivable_payment__isnull=False, expense__isnull=True)
                        | Q(sale__isnull=True, receivable_payment__isnull=True, expense__isnull=False)
                    )
                ),
                name="financial_movement_valid_source",
            ),
            models.UniqueConstraint(
                fields=("business", "idempotency_key"),
                condition=~Q(idempotency_key=""),
                name="financial_movement_business_idempotency_key",
            ),
            models.UniqueConstraint(
                fields=("sale", "event_type"),
                condition=Q(sale__isnull=False),
                name="financial_movement_sale_event_unique",
            ),
            models.UniqueConstraint(
                fields=("expense", "event_type"),
                condition=Q(expense__isnull=False),
                name="financial_movement_expense_event_unique",
            ),
        ]

    def clean(self):
        """Keep event/source, tenant, currency and reversal invariants coherent."""
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Amount must be positive."
        if self.business_id and self.currency != self.business.primary_currency:
            errors["currency"] = "Currency must match the Business primary currency."

        sources = {
            "sale": self.sale,
            "receivable_payment": self.receivable_payment,
            "expense": self.expense,
        }
        present_sources = [name for name, value in sources.items() if value is not None]
        if self.reversal_of_id:
            if present_sources:
                errors["reversal_of"] = "A reversal cannot have a separate source."
            elif self.event_type != self.EventType.EXPENSE_REVERSAL:
                errors["event_type"] = "A reversal must use EXPENSE_REVERSAL."
            elif not self.reason.strip():
                errors["reason"] = "A reversal reason is required."
            else:
                original = self.reversal_of
                if original.event_type != self.EventType.EXPENSE_PAYMENT:
                    errors["reversal_of"] = "Only expense payments can be reversed in this version."
                if original.business_id != self.business_id:
                    errors["business"] = "The reversal must belong to the original Business."
                if self.amount != original.amount or self.currency != original.currency:
                    errors["amount"] = "A reversal must retain the original amount and currency."
                if self.payment_method != original.payment_method:
                    errors["payment_method"] = "A reversal must retain the original payment method."
                if self.direction == original.direction:
                    errors["direction"] = "A reversal must use the opposite direction."
        else:
            expected_source = {
                self.EventType.SALE_PAYMENT: "sale",
                self.EventType.RECEIVABLE_PAYMENT: "receivable_payment",
                self.EventType.EXPENSE_PAYMENT: "expense",
            }.get(self.event_type)
            if expected_source is None:
                errors["event_type"] = "EXPENSE_REVERSAL requires reversal_of."
            elif present_sources != [expected_source]:
                errors["event_type"] = "The event type does not match its source."
            elif self.business_id and sources[expected_source].business_id != self.business_id:
                errors[expected_source] = "The source must belong to the same Business."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Financial movements are immutable.")
        if not self.public_id:
            self.public_id = generate_financial_movement_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial movements cannot be deleted.")
