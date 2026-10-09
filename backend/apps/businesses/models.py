import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CarriIdentity
from apps.common.choices import PaymentMethod

from .identifiers import (
    generate_business_member_invitation_public_id,
    generate_business_member_public_id,
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
        REMOVED = "REMOVED", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(
        max_length=12,
        unique=True,
        editable=False,
        db_index=True,
    )
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
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.EMPLOYEE,
    )
    is_owner = models.BooleanField(default=False)
    title = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_by = models.ForeignKey(
        CarriIdentity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="business_members_suspended",
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        CarriIdentity,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="business_members_removed",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["identity", "business"],
                name="unique_business_identity",
            ),
            models.UniqueConstraint(
                fields=["business"],
                condition=Q(is_owner=True),
                name="unique_business_owner",
            ),
        ]

    def save(self, *args, **kwargs):
        # Transitional compatibility for trusted code that still creates the
        # initial owner through the legacy role. Authorization never reads role.
        if self._state.adding and self.role == self.Role.OWNER and not self.is_owner:
            self.is_owner = True
            if not self.title:
                self.title = "Gérant"
        if not self.public_id:
            self.public_id = generate_business_member_public_id()
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        errors = {}

        if not self.pk or not type(self).objects.filter(pk=self.pk).exists():
            if self.is_owner and not self.title:
                errors["title"] = "An owner must have a title."
            if self.is_owner and self.status != self.Status.ACTIVE:
                errors["status"] = "A business owner must be active."
            if errors:
                raise ValidationError(errors)
            return

        previous = type(self).objects.get(pk=self.pk)

        if previous.status == self.Status.REMOVED and self.status != self.Status.REMOVED:
            errors["status"] = "A removed business member cannot be reactivated."

        removes_active_owner = previous.is_owner and (
            not self.is_owner or self.status != self.Status.ACTIVE
        )
        if removes_active_owner:
            has_another_active_owner = type(self).objects.filter(
                business=self.business,
                is_owner=True,
                status=self.Status.ACTIVE,
            ).exclude(pk=self.pk).exists()
            if not has_another_active_owner:
                errors["is_owner"] = "A business must retain an active owner."

        if errors:
            raise ValidationError(errors)

    def delete(self, *args, **kwargs):
        raise ValidationError("Business members must be removed logically.")


class BusinessMemberPermission(models.Model):
    class Permission(models.TextChoices):
        VIEW_MEMBERS = "VIEW_MEMBERS", "View members"
        MANAGE_MEMBERS = "MANAGE_MEMBERS", "Manage members"
        UPDATE_BUSINESS = "UPDATE_BUSINESS", "Update business"
        VIEW_PAYMENT_METHODS = "VIEW_PAYMENT_METHODS", "View payment methods"
        MANAGE_PAYMENT_METHODS = "MANAGE_PAYMENT_METHODS", "Manage payment methods"
        VIEW_CUSTOMERS = "VIEW_CUSTOMERS", "View customers"
        MANAGE_CUSTOMERS = "MANAGE_CUSTOMERS", "Manage customers"
        VIEW_CATALOG = "VIEW_CATALOG", "View catalog"
        MANAGE_CATALOG = "MANAGE_CATALOG", "Manage catalog"
        VIEW_INVENTORY = "VIEW_INVENTORY", "View inventory"
        MANAGE_EXPENSE_CATEGORIES = "MANAGE_EXPENSE_CATEGORIES", "Manage expense categories"
        CREATE_EXPENSES = "CREATE_EXPENSES", "Create expenses"
        VIEW_EXPENSES = "VIEW_EXPENSES", "View expenses"
        MANAGE_EXPENSES = "MANAGE_EXPENSES", "Manage expenses"
        VIEW_PURCHASES = "VIEW_PURCHASES", "View purchases"
        MANAGE_PURCHASES = "MANAGE_PURCHASES", "Manage purchases"
        USE_POS = "USE_POS", "Use point of sale"
        VIEW_SALES = "VIEW_SALES", "View sales"
        MANAGE_SALES = "MANAGE_SALES", "Manage sales"
        MANAGE_SALE_RETURNS = "MANAGE_SALE_RETURNS", "Manage sale returns"
        VIEW_RECEIVABLES = "VIEW_RECEIVABLES", "View receivables"
        MANAGE_RECEIVABLES = "MANAGE_RECEIVABLES", "Manage receivables"
        VIEW_FINANCIAL_SUMMARY = "VIEW_FINANCIAL_SUMMARY", "View financial summary"
        MANAGE_INVENTORY = "MANAGE_INVENTORY", "Manage inventory"
        VIEW_DASHBOARD = "VIEW_DASHBOARD", "View dashboard"
        VIEW_PROFITABILITY = "VIEW_PROFITABILITY", "View profitability"
        VIEW_REPORTS = "VIEW_REPORTS", "View reports"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member = models.ForeignKey(
        BusinessMember,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    permission = models.CharField(max_length=40, choices=Permission.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member", "permission"],
                name="unique_member_permission",
            )
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.member and self.member.is_owner:
            raise ValidationError("Owners have all permissions by design.")
        if self.member and self.member.status != BusinessMember.Status.ACTIVE:
            raise ValidationError("Permissions can only be granted to active members.")


class BusinessMemberInvitation(models.Model):
    """Email invitation to join a Business, before any membership exists."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        REVOKED = "REVOKED", "Revoked"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.CharField(
        max_length=12,
        unique=True,
        editable=False,
        db_index=True,
    )
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="member_invitations",
    )
    email = models.EmailField()
    normalized_email = models.EmailField(db_index=True)
    title = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    invited_by = models.ForeignKey(
        CarriIdentity,
        on_delete=models.PROTECT,
        related_name="business_member_invitations_sent",
    )
    accepted_by = models.ForeignKey(
        CarriIdentity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_member_invitations_accepted",
    )
    member = models.ForeignKey(
        BusinessMember,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_member_invitations",
    )
    acted_at = models.DateTimeField(null=True, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    resend_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "normalized_email"],
                condition=Q(status="PENDING"),
                name="unique_pending_business_member_invitation",
            ),
            models.UniqueConstraint(
                fields=["business", "normalized_email"],
                condition=Q(status="EXPIRED"),
                name="unique_expired_business_member_invitation",
            ),
        ]
        indexes = [
            models.Index(
                fields=["business", "status", "created_at"],
                name="biz_member_invitation_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = generate_business_member_invitation_public_id()
        self.normalized_email = self.normalize_email(self.email)
        super().save(*args, **kwargs)

    @staticmethod
    def normalize_email(email):
        return (email or "").strip().lower()

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()
