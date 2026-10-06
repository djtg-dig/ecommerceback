import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.models import CarriIdentity
from apps.common.choices import PaymentMethod

from .identifiers import (
    generate_business_payment_method_public_id,
    generate_business_public_id,
)


class Business(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        ARCHIVED = "ARCHIVED", "Archived"

    class Currency(models.TextChoices):
        CDF = "CDF", "CDF"
        USD = "USD", "USD"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(
        max_length=12,
        unique=True,
        editable=False,
        db_index=True,
    )
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    address = models.TextField(blank=True)
    zone = models.CharField(max_length=120, blank=True)
    primary_currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.CDF,
    )
    phone = models.CharField(max_length=40, blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        """Preserve the Business financial currency after its initial choice.

        Operational amounts are snapshots in this currency; changing it later would
        make existing Sale, Purchase, Expense and Receivable history ambiguous.
        """
        if self.pk:
            previous_currency = type(self).objects.filter(pk=self.pk).values_list(
                "primary_currency",
                flat=True,
            ).first()
            if previous_currency and previous_currency != self.primary_currency:
                raise ValidationError(
                    {"primary_currency": "Business primary_currency is immutable."}
                )

        if not self.public_id:
            self.public_id = generate_business_public_id()

        super().save(*args, **kwargs)


class BusinessCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class BusinessPaymentMethod(models.Model):
    """A Business-configured payment method, never a balance-bearing account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(max_length=12, unique=True, editable=False, db_index=True)
    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="payment_methods")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=PaymentMethod.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("business", "name"), name="business_payment_method_unique_name")]

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = generate_business_payment_method_public_id()
        return super().save(*args, **kwargs)


class BusinessCategoryMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="category_memberships",
    )
    category = models.ForeignKey(
        BusinessCategory,
        on_delete=models.PROTECT,
        related_name="business_memberships",
    )
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business", "category"],
                name="unique_business_category",
            ),
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(is_primary=True),
                name="one_primary_business_category",
            ),
        ]


class BusinessMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        MANAGER = "MANAGER", "Manager"
        EMPLOYEE = "EMPLOYEE", "Employee"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.ForeignKey(
        CarriIdentity,
        on_delete=models.PROTECT,
        related_name="business_memberships",
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.PROTECT,
        related_name="members",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["identity", "business"],
                name="unique_business_identity",
            )
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.pk or not type(self).objects.filter(pk=self.pk).exists():
            return

        previous = type(self).objects.get(pk=self.pk)
        removes_active_owner = (
            previous.role == self.Role.OWNER
            and previous.status == self.Status.ACTIVE
            and (
                self.role != self.Role.OWNER
                or self.status != self.Status.ACTIVE
            )
        )
        if removes_active_owner:
            has_another_active_owner = type(self).objects.filter(
                business=self.business,
                role=self.Role.OWNER,
                status=self.Status.ACTIVE,
            ).exclude(pk=self.pk).exists()

            if not has_another_active_owner:
                raise ValidationError("A business must retain an active owner.")
