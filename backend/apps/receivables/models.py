import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.choices import PaymentMethod


class Receivable(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    sale = models.OneToOneField("sales.Sale", on_delete=models.PROTECT, related_name="receivable")
    customer = models.ForeignKey("sales.Customer", on_delete=models.PROTECT)
    currency = models.CharField(max_length=3)
    original_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(original_amount__gt=0), name="receivable_original_positive")]

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_receivable_public_id

        if not self.public_id:
            self.public_id = generate_receivable_public_id()
        return super().save(*args, **kwargs)

    @property
    def paid_amount(self):
        from django.db.models import Sum
        return self.payments.aggregate(total=Sum("amount"))["total"] or 0

    @property
    def adjusted_amount(self):
        from django.db.models import Sum
        return self.adjustments.aggregate(total=Sum("amount"))["total"] or 0

    @property
    def balance(self):
        return self.original_amount - self.paid_amount - self.adjusted_amount

    @property
    def is_overdue(self):
        from django.utils import timezone
        return self.status != self.Status.PAID and self.due_date and self.due_date < timezone.localdate()


class ReceivablePayment(models.Model):
    """Immutable record of one real collection against a receivable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=255, blank=True)
    idempotency_fingerprint = models.CharField(max_length=64, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="receivable_payment_positive"),
            models.UniqueConstraint(
                fields=("business", "idempotency_key"),
                condition=~Q(idempotency_key=""),
                name="receivable_payment_business_idempotency_key",
            ),
        ]

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_receivable_payment_public_id

        if not self._state.adding:
            raise ValidationError("Receivable payments are immutable.")
        if not self.public_id:
            self.public_id = generate_receivable_payment_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Receivable payments cannot be deleted.")


class ReceivableAdjustment(models.Model):
    """Immutable non-cash receivable reduction produced by a sale return."""
    class Type(models.TextChoices):
        RETURN_CREDIT = "RETURN_CREDIT", "Return credit"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT)
    receivable = models.ForeignKey(Receivable, on_delete=models.PROTECT, related_name="adjustments")
    sale_return = models.OneToOneField("sales.SaleReturn", on_delete=models.PROTECT, related_name="receivable_adjustment")
    adjustment_type = models.CharField(max_length=20, choices=Type.choices, default=Type.RETURN_CREDIT)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    created_by = models.ForeignKey("accounts.CarriIdentity", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="receivable_adjustment_positive")]

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_receivable_adjustment_public_id
        if not self._state.adding:
            raise ValidationError("Receivable adjustments are immutable.")
        if not self.public_id:
            self.public_id = generate_receivable_adjustment_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Receivable adjustments cannot be deleted.")
