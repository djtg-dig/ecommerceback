import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.choices import PaymentMethod


class ExpenseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False)
    business = models.ForeignKey(
        "businesses.Business", on_delete=models.PROTECT, related_name="expense_categories"
    )
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("business", "code"), name="expense_category_business_code"
            )
        ]
        ordering = ("sort_order", "name")

    def clean(self):
        if not self.pk:
            return
        previous = type(self).objects.filter(pk=self.pk).first()
        if previous is None:
            return
        if previous.public_id != self.public_id:
            raise ValidationError({"public_id": "The public identifier is immutable."})
        if previous.is_system and any(
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
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"

    class Currency(models.TextChoices):
        CDF = "CDF", "CDF"
        USD = "USD", "USD"

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
    created_by = models.ForeignKey(
        "accounts.CarriIdentity", on_delete=models.PROTECT, related_name="expenses"
    )
    cancelled_by = models.ForeignKey(
        "accounts.CarriIdentity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cancelled_expenses",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-expense_date", "-created_at")
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="expense_amount_positive")
        ]

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Amount must be positive."
        if self.category_id and self.business_id and self.category.business_id != self.business_id:
            errors["category"] = "The category must belong to the same business."
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None and previous.public_id != self.public_id:
                errors["public_id"] = "The public identifier is immutable."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from apps.businesses.identifiers import generate_expense_public_id

        if not self.public_id:
            self.public_id = generate_expense_public_id()
        self.full_clean()
        return super().save(*args, **kwargs)
