import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum

from apps.common.choices import PaymentMethod


class ExpenseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="expense_categories")
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("business", "code"), name="expense_category_business_code")]
        ordering = ("sort_order", "name")

    def clean(self):
        if not self.pk:
            return
        previous = type(self).objects.filter(pk=self.pk).first()
        if previous and previous.public_id != self.public_id:
            raise ValidationError({"public_id": "The public identifier is immutable."})
        if previous and previous.is_system and any(
            getattr(previous, field) != getattr(self, field)
            for field in ("business_id", "code", "name", "description", "is_system")
        ):
            raise ValidationError("System expense categories are immutable.")

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_expense_category_public_id
        if not self.public_id:
            self.public_id = generate_expense_category_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)


class Expense(models.Model):
    """A recognised business charge; it does not itself represent a cash outflow."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"

    class Currency(models.TextChoices):
        CDF = "CDF", "CDF"
        USD = "USD", "USD"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    expense_date = models.DateField()
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT, related_name="expenses")
    cancelled_by = models.ForeignKey("accounts.CarriIdentity", null=True, blank=True, on_delete=models.PROTECT, related_name="cancelled_expenses")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-expense_date", "-created_at")
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive")]

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Amount must be positive."
        if self.category_id and self.business_id and self.category.business_id != self.business_id:
            errors["category"] = "The category must belong to the same business."
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.public_id != self.public_id:
                errors["public_id"] = "The public identifier is immutable."
            if previous and previous.amount != self.amount:
                paid_amount = self.payments.filter(
                    reversed_at__isnull=True
                ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
                if self.amount < paid_amount:
                    errors["amount"] = (
                        "Amount cannot be lower than the total already paid."
                    )
        if errors:
            raise ValidationError(errors)

    @property
    def paid_amount(self):
        """Sum active payments only; reversed payments remain visible in history."""
        if hasattr(self, "computed_paid_amount"):
            return self.computed_paid_amount
        return self.payments.filter(reversed_at__isnull=True).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    @property
    def balance(self):
        return self.amount - self.paid_amount

    @property
    def payment_status(self):
        if self.paid_amount == 0:
            return self.PaymentStatus.UNPAID
        if self.paid_amount == self.amount:
            return self.PaymentStatus.PAID
        return self.PaymentStatus.PARTIALLY_PAID

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_expense_public_id
        if not self.public_id:
            self.public_id = generate_expense_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)


class ExpensePayment(models.Model):
    """Immutable monetary settlement of an Expense, with auditable reversal metadata."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    paid_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT, related_name="expense_payments")
    idempotency_key = models.CharField(max_length=255, blank=True)
    idempotency_fingerprint = models.CharField(max_length=64, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey("accounts.CarriIdentity", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_expense_payments")
    reversal_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-paid_at", "-created_at")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expense_payment_amount_positive"),
            models.UniqueConstraint(fields=("expense", "idempotency_key"), condition=~Q(idempotency_key=""), name="expense_payment_idempotency_key"),
        ]

    @property
    def is_reversed(self):
        return self.reversed_at is not None

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_expense_payment_public_id
        if not self._state.adding:
            previous = type(self).objects.get(pk=self.pk)
            allowed = {"reversed_at", "reversed_by", "reversal_reason"}
            changed = {
                field.name
                for field in self._meta.fields
                if getattr(previous, field.attname) != getattr(self, field.attname)
            }
            if not changed.issubset(allowed):
                raise ValidationError("Expense payments are immutable.")
        if not self.public_id:
            self.public_id = generate_expense_payment_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Expense payments cannot be deleted.")
