import uuid
from decimal import Decimal

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


class Currency(models.Model):
    """Platform currency reference data. Amounts always retain their own code."""

    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=80)
    symbol = models.CharField(max_length=12)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("code",)
        constraints = [models.CheckConstraint(condition=models.Q(decimal_places__lte=6), name="currency_decimal_places_lte_six")]

    def clean(self):
        super().clean()
        self.code = self.code.upper()


class BusinessCurrency(models.Model):
    """A currency enabled by one tenant; only one row can be primary."""

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="currencies")
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="businesses")
    is_primary = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_primary", "currency__code")
        constraints = [
            models.UniqueConstraint(fields=("business", "currency"), name="business_currency_unique"),
            models.UniqueConstraint(fields=("business",), condition=models.Q(is_primary=True), name="business_currency_one_primary"),
            models.CheckConstraint(condition=models.Q(is_primary=False) | models.Q(is_enabled=True), name="business_currency_primary_enabled"),
        ]


class BusinessExchangeRate(models.Model):
    """Manual, tenant-scoped rate: one unit of ``from_currency`` equals ``rate`` units of ``to_currency``."""

    business = models.ForeignKey(Business, on_delete=models.PROTECT, related_name="exchange_rates")
    from_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="exchange_rates_from")
    to_currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="exchange_rates_to")
    rate = models.DecimalField(max_digits=24, decimal_places=12)
    effective_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-effective_at", "-created_at")
        indexes = [models.Index(fields=("business", "from_currency", "to_currency", "is_active", "effective_at"), name="business_rate_lookup_idx")]
        constraints = [
            models.CheckConstraint(condition=models.Q(rate__gt=Decimal("0")), name="business_exchange_rate_positive"),
            models.CheckConstraint(condition=~models.Q(from_currency=models.F("to_currency")), name="business_exchange_rate_distinct_currencies"),
            models.CheckConstraint(condition=models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=models.F("effective_at")), name="business_exchange_rate_expiry_after_effective"),
        ]


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

        # Atomic permissions. Legacy codes above remain temporarily available
        # until migration 0012 has expanded persisted memberships/invitations.
        BUSINESS_UPDATE = "BUSINESS_UPDATE", "Update business"
        PAYMENT_METHOD_VIEW = "PAYMENT_METHOD_VIEW", "View payment methods"
        PAYMENT_METHOD_CREATE = "PAYMENT_METHOD_CREATE", "Create payment methods"
        PAYMENT_METHOD_UPDATE = "PAYMENT_METHOD_UPDATE", "Update payment methods"
        MEMBER_VIEW = "MEMBER_VIEW", "View members"
        MEMBER_UPDATE = "MEMBER_UPDATE", "Update members"
        MEMBER_SUSPEND = "MEMBER_SUSPEND", "Suspend members"
        MEMBER_REACTIVATE = "MEMBER_REACTIVATE", "Reactivate members"
        MEMBER_REMOVE = "MEMBER_REMOVE", "Remove members"
        MEMBER_PERMISSION_VIEW = "MEMBER_PERMISSION_VIEW", "View member permissions"
        MEMBER_PERMISSION_GRANT = "MEMBER_PERMISSION_GRANT", "Grant member permissions"
        MEMBER_PERMISSION_REVOKE = "MEMBER_PERMISSION_REVOKE", "Revoke member permissions"
        INVITATION_VIEW = "INVITATION_VIEW", "View invitations"
        INVITATION_CREATE = "INVITATION_CREATE", "Create invitations"
        INVITATION_RESEND = "INVITATION_RESEND", "Resend invitations"
        INVITATION_REVOKE = "INVITATION_REVOKE", "Revoke invitations"
        PRODUCT_VIEW = "PRODUCT_VIEW", "View products"
        PRODUCT_CREATE = "PRODUCT_CREATE", "Create products"
        PRODUCT_UPDATE = "PRODUCT_UPDATE", "Update products"
        PRODUCT_DELETE = "PRODUCT_DELETE", "Delete products"
        PRODUCT_DEACTIVATE = "PRODUCT_DEACTIVATE", "Archive products"
        PRODUCT_VARIANT_VIEW = "PRODUCT_VARIANT_VIEW", "View product variants"
        PRODUCT_VARIANT_CREATE = "PRODUCT_VARIANT_CREATE", "Create product variants"
        PRODUCT_VARIANT_UPDATE = "PRODUCT_VARIANT_UPDATE", "Update product variants"
        INVENTORY_VIEW = "INVENTORY_VIEW", "View inventory"
        INVENTORY_INITIALIZE = "INVENTORY_INITIALIZE", "Initialize inventory"
        INVENTORY_IN = "INVENTORY_IN", "Record stock entry"
        INVENTORY_OUT = "INVENTORY_OUT", "Record stock exit"
        INVENTORY_ADJUST = "INVENTORY_ADJUST", "Adjust inventory"
        INVENTORY_MOVEMENT_VIEW = "INVENTORY_MOVEMENT_VIEW", "View inventory movements"
        SUPPLIER_VIEW = "SUPPLIER_VIEW", "View suppliers"
        SUPPLIER_CREATE = "SUPPLIER_CREATE", "Create suppliers"
        SUPPLIER_UPDATE = "SUPPLIER_UPDATE", "Update suppliers"
        SUPPLIER_DEACTIVATE = "SUPPLIER_DEACTIVATE", "Deactivate suppliers"
        SUPPLIER_REACTIVATE = "SUPPLIER_REACTIVATE", "Reactivate suppliers"
        PURCHASE_VIEW = "PURCHASE_VIEW", "View purchases"
        PURCHASE_CREATE = "PURCHASE_CREATE", "Create purchases"
        PURCHASE_UPDATE = "PURCHASE_UPDATE", "Update purchases"
        PURCHASE_CONFIRM = "PURCHASE_CONFIRM", "Confirm purchases"
        PURCHASE_RECEIVE = "PURCHASE_RECEIVE", "Receive purchases"
        PURCHASE_CANCEL = "PURCHASE_CANCEL", "Cancel purchases"
        PURCHASE_LINE_VIEW = "PURCHASE_LINE_VIEW", "View purchase lines"
        PURCHASE_LINE_CREATE = "PURCHASE_LINE_CREATE", "Create purchase lines"
        PURCHASE_LINE_UPDATE = "PURCHASE_LINE_UPDATE", "Update purchase lines"
        PURCHASE_LINE_DELETE = "PURCHASE_LINE_DELETE", "Delete purchase lines"
        SUPPLIER_PAYMENT_VIEW = "SUPPLIER_PAYMENT_VIEW", "View supplier payments"
        SUPPLIER_PAYMENT_CREATE = "SUPPLIER_PAYMENT_CREATE", "Create supplier payments"
        SUPPLIER_PAYMENT_REVERSE = "SUPPLIER_PAYMENT_REVERSE", "Reverse supplier payments"
        CUSTOMER_VIEW = "CUSTOMER_VIEW", "View customers"
        CUSTOMER_CREATE = "CUSTOMER_CREATE", "Create customers"
        CUSTOMER_UPDATE = "CUSTOMER_UPDATE", "Update customers"
        CUSTOMER_DEACTIVATE = "CUSTOMER_DEACTIVATE", "Deactivate customers"
        CUSTOMER_REACTIVATE = "CUSTOMER_REACTIVATE", "Reactivate customers"
        SALE_VIEW = "SALE_VIEW", "View sales"
        SALE_CREATE = "SALE_CREATE", "Create sales"
        SALE_UPDATE = "SALE_UPDATE", "Update sales"
        SALE_COMPLETE = "SALE_COMPLETE", "Complete sales"
        SALE_CANCEL = "SALE_CANCEL", "Cancel sales"
        SALE_LINE_VIEW = "SALE_LINE_VIEW", "View sale lines"
        SALE_LINE_CREATE = "SALE_LINE_CREATE", "Create sale lines"
        SALE_RETURN_VIEW = "SALE_RETURN_VIEW", "View sale returns"
        SALE_RETURN = "SALE_RETURN", "Create sale returns"
        RECEIVABLE_VIEW = "RECEIVABLE_VIEW", "View receivables"
        RECEIVABLE_UPDATE = "RECEIVABLE_UPDATE", "Update receivables"
        RECEIVABLE_PAYMENT_VIEW = "RECEIVABLE_PAYMENT_VIEW", "View receivable payments"
        RECEIVABLE_PAYMENT_CREATE = "RECEIVABLE_PAYMENT_CREATE", "Create receivable payments"
        FINANCIAL_SUMMARY_VIEW = "FINANCIAL_SUMMARY_VIEW", "View financial summary"
        FINANCIAL_MOVEMENT_VIEW = "FINANCIAL_MOVEMENT_VIEW", "View financial movements"
        EXPENSE_CATEGORY_VIEW = "EXPENSE_CATEGORY_VIEW", "View expense categories"
        EXPENSE_CATEGORY_CREATE = "EXPENSE_CATEGORY_CREATE", "Create expense categories"
        EXPENSE_CATEGORY_UPDATE = "EXPENSE_CATEGORY_UPDATE", "Update expense categories"
        EXPENSE_VIEW = "EXPENSE_VIEW", "View expenses"
        EXPENSE_CREATE = "EXPENSE_CREATE", "Create expenses"
        EXPENSE_UPDATE = "EXPENSE_UPDATE", "Update expenses"
        EXPENSE_CANCEL = "EXPENSE_CANCEL", "Cancel expenses"
        EXPENSE_PAYMENT_VIEW = "EXPENSE_PAYMENT_VIEW", "View expense payments"
        EXPENSE_PAYMENT_CREATE = "EXPENSE_PAYMENT_CREATE", "Create expense payments"
        EXPENSE_PAYMENT_REVERSE = "EXPENSE_PAYMENT_REVERSE", "Reverse expense payments"
        DASHBOARD_VIEW = "DASHBOARD_VIEW", "View dashboard"
        PROFITABILITY_VIEW = "PROFITABILITY_VIEW", "View profitability"
        SALE_REPORT_VIEW = "SALE_REPORT_VIEW", "View sales report"
        PURCHASE_REPORT_VIEW = "PURCHASE_REPORT_VIEW", "View purchase report"
        EXPENSE_RECEIVABLE_REPORT_VIEW = "EXPENSE_RECEIVABLE_REPORT_VIEW", "View expense and receivable report"

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
    permissions = models.JSONField(default=list, blank=True)
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
    declined_by = models.ForeignKey(
        CarriIdentity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="business_member_invitations_declined",
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
