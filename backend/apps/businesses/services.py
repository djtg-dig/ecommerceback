"""Application services for explicit Business lifecycle operations."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.common.choices import PaymentMethod

from .identifiers import generate_business_public_id
from .models import (
    Business,
    BusinessCategory,
    BusinessCategoryMembership,
    BusinessMember,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from .permissions import validate_permission

MAX_PUBLIC_ID_ATTEMPTS = 5
DEFAULT_PAYMENT_METHODS = (
    ("Argent liquide", PaymentMethod.CASH),
    ("Mobile Money", PaymentMethod.MOBILE_MONEY),
    ("Virement bancaire", PaymentMethod.BANK_TRANSFER),
    ("Carte", PaymentMethod.CARD),
    ("Autre", PaymentMethod.OTHER),
)


def ensure_default_payment_methods(business):
    """Create standard methods when absent, without creating financial balances."""
    for name, category in DEFAULT_PAYMENT_METHODS:
        BusinessPaymentMethod.objects.get_or_create(
            business=business, name=name, defaults={"category": category}
        )


def create_business(identity, validated_data):
    """
    Create a Business, its active OWNER and its reference data as one transaction.

    The Expenses service initializes the standard expense categories inside the
    same transaction. Any failure during that initialization rolls back the
    Business, OWNER and category memberships together; callers never receive a
    partially initialized Business.
    """
    categories = validated_data.pop("categories", [])
    primary_category = validated_data.pop("primary_category", None)

    active_categories = {
        category.code: category
        for category in BusinessCategory.objects.filter(
            code__in=categories,
            is_active=True,
        )
    }
    if len(active_categories) != len(set(categories)) or (
        primary_category and primary_category not in active_categories
    ):
        raise ValueError("Invalid business categories.")

    for _ in range(MAX_PUBLIC_ID_ATTEMPTS):
        try:
            with transaction.atomic():
                business = Business.objects.create(
                    public_id=generate_business_public_id(),
                    **validated_data,
                )

                BusinessMember.objects.create(
                    business=business,
                    identity=identity,
                    role=BusinessMember.Role.OWNER,
                    is_owner=True,
                    title="Gérant",
                    status=BusinessMember.Status.ACTIVE,
                )

                for code, category in active_categories.items():
                    BusinessCategoryMembership.objects.create(
                        business=business,
                        category=category,
                        is_primary=code == primary_category,
                    )

                from apps.expenses.services import ensure_default_expense_categories

                ensure_default_expense_categories(business)
                ensure_default_payment_methods(business)

                return business
        except IntegrityError:
            continue

    raise RuntimeError("Unable to allocate business public identifier.")


def replace_categories(business, codes, primary_category):
    """Replace a Business's selected commercial categories in one transaction."""
    active_categories = {
        category.code: category
        for category in BusinessCategory.objects.filter(
            code__in=codes,
            is_active=True,
        )
    }
    if len(active_categories) != len(set(codes)) or (
        primary_category and primary_category not in active_categories
    ):
        raise ValueError("Invalid business categories.")

    with transaction.atomic():
        BusinessCategoryMembership.objects.filter(business=business).delete()

        for code, category in active_categories.items():
            BusinessCategoryMembership.objects.create(
                business=business,
                category=category,
                is_primary=code == primary_category,
            )


def grant_permission(actor_member, member, permission):
    """Let an active owner grant one explicit permission in their Business."""
    validate_permission(permission)

    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        if (
            not actor.is_owner
            or actor.status != BusinessMember.Status.ACTIVE
            or actor.business_id != target.business_id
        ):
            raise ValidationError("Only the active Business owner can grant permissions.")
        if business.status != Business.Status.ACTIVE:
            raise ValidationError("Permissions cannot be changed for an inactive Business.")
        if target.is_owner:
            raise ValidationError("Owners already have all permissions.")
        if target.status != BusinessMember.Status.ACTIVE:
            raise ValidationError("Only active members can receive permissions.")

        permission_row, _ = BusinessMemberPermission.objects.get_or_create(
            member=target,
            permission=permission,
        )
        return permission_row


def revoke_permission(actor_member, member, permission):
    """Let an active owner revoke one explicit permission in their Business."""
    validate_permission(permission)

    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        if (
            not actor.is_owner
            or actor.status != BusinessMember.Status.ACTIVE
            or actor.business_id != target.business_id
        ):
            raise ValidationError("Only the active Business owner can revoke permissions.")
        if business.status != Business.Status.ACTIVE:
            raise ValidationError("Permissions cannot be changed for an inactive Business.")
        if target.is_owner:
            raise ValidationError("Owner permissions are implicit and cannot be revoked.")

        BusinessMemberPermission.objects.filter(
            member=target,
            permission=permission,
        ).delete()
