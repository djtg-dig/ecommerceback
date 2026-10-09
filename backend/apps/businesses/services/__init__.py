"""Application services for explicit Business lifecycle operations."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.choices import PaymentMethod

from ..identifiers import generate_business_public_id
from ..models import (
    Business,
    BusinessCategory,
    BusinessCategoryMembership,
    BusinessMember,
    BusinessMemberPermission,
    BusinessPaymentMethod,
)
from ..permissions import has_permission, validate_permission

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


def remove_member(actor_member, member):
    """Logically remove a non-owner and revoke access in one locked transaction."""
    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        actor.business = business

        if actor.business_id != target.business_id or not has_permission(
            actor,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        ):
            raise ValidationError("An authorized member manager is required.")
        if target.is_owner:
            raise ValidationError("A Business owner cannot be removed.")
        if actor.pk == target.pk:
            raise ValidationError("A member cannot remove themselves.")
        if target.status == BusinessMember.Status.REMOVED:
            return target

        target.status = BusinessMember.Status.REMOVED
        target.removed_at = timezone.now()
        target.removed_by = actor.identity
        target.save(
            update_fields=(
                "status",
                "removed_at",
                "removed_by",
                "updated_at",
            )
        )
        target.permissions.all().delete()
        return target


def update_member_title(actor_member, member, title):
    """Change one descriptive title without touching any authorization data."""
    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        actor.business = business

        if actor.business_id != target.business_id or not has_permission(
            actor,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        ):
            raise ValidationError("An authorized member manager is required.")
        if target.status == BusinessMember.Status.REMOVED:
            raise ValidationError("A removed business member cannot be updated.")

        target.title = title
        target.save(update_fields=("title", "updated_at"))
        return target


def suspend_member(actor_member, member):
    """Suspend an active non-owner; permissions stay but become inert."""
    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        actor.business = business

        if actor.business_id != target.business_id or not has_permission(
            actor,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        ):
            raise ValidationError("An authorized member manager is required.")
        if target.is_owner:
            raise ValidationError("A Business owner cannot be suspended.")
        if actor.pk == target.pk:
            raise ValidationError("A member cannot suspend themselves.")
        if target.status == BusinessMember.Status.REMOVED:
            raise ValidationError("A removed business member cannot be suspended.")
        if target.status == BusinessMember.Status.SUSPENDED:
            return target

        target.status = BusinessMember.Status.SUSPENDED
        target.suspended_at = timezone.now()
        target.suspended_by = actor.identity
        target.save(
            update_fields=(
                "status",
                "suspended_at",
                "suspended_by",
                "updated_at",
            )
        )
        return target


def reactivate_member(actor_member, member):
    """Reactivate a suspended member with their existing permissions."""
    with transaction.atomic():
        actor = BusinessMember.objects.select_for_update().get(pk=actor_member.pk)
        target = BusinessMember.objects.select_for_update().get(pk=member.pk)
        business = Business.objects.select_for_update().get(pk=actor.business_id)
        actor.business = business

        if actor.business_id != target.business_id or not has_permission(
            actor,
            BusinessMemberPermission.Permission.MANAGE_MEMBERS,
            write=True,
        ):
            raise ValidationError("An authorized member manager is required.")
        if target.is_owner:
            raise ValidationError("A Business owner is already active.")
        if target.status == BusinessMember.Status.REMOVED:
            raise ValidationError("A removed business member cannot be reactivated.")
        if target.status == BusinessMember.Status.ACTIVE:
            return target

        target.status = BusinessMember.Status.ACTIVE
        target.suspended_at = None
        target.suspended_by = None
        target.save(
            update_fields=(
                "status",
                "suspended_at",
                "suspended_by",
                "updated_at",
            )
        )
        return target
