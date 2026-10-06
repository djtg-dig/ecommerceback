"""Application services for explicit Business lifecycle operations."""

from django.db import IntegrityError, transaction

from .identifiers import generate_business_public_id
from .models import Business, BusinessCategory, BusinessCategoryMembership, BusinessMember

MAX_PUBLIC_ID_ATTEMPTS = 5


def create_business(identity, validated_data):
    """
    Create a Business, its first active owner and its owned reference data atomically.

    Expense categories are initialized here, instead of from a signal, so a caller
    never observes a newly created Business without its standard expense taxonomy.
    An integrity error rolls back the complete unit of work before the public-ID
    allocation is retried.
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
                    status=BusinessMember.Status.ACTIVE,
                )
                for code, category in active_categories.items():
                    BusinessCategoryMembership.objects.create(
                        business=business,
                        category=category,
                        is_primary=code == primary_category,
                    )

                # The Expenses app owns the taxonomy; Businesses only orchestrates it.
                from apps.expenses.services import ensure_default_expense_categories

                ensure_default_expense_categories(business)
                return business
        except IntegrityError:
            continue

    raise RuntimeError("Unable to allocate business public identifier.")


def replace_categories(business, codes, primary_category):
    """Replace a Business's selected commercial categories as one transaction."""
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
