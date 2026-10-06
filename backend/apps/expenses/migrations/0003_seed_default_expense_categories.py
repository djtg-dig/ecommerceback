"""Seed the standard Expense taxonomy for Businesses that predate Expenses."""

import secrets

from django.db import migrations

STANDARD_EXPENSE_CATEGORIES = (
    ("RENT", "Loyer"),
    ("ELECTRICITY", "Électricité"),
    ("WATER", "Eau"),
    ("INTERNET", "Internet"),
    ("TRANSPORT", "Transport"),
    ("SALARY", "Salaire"),
    ("MAINTENANCE", "Maintenance"),
    ("SUPPLIES", "Fournitures"),
    ("TAX", "Taxe / impôt"),
    ("MARKETING", "Marketing"),
    ("OTHER", "Autre"),
)
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_public_id():
    """Generate an EC identifier without importing runtime application models."""
    return "EC" + "".join(secrets.choice(ALPHABET) for _ in range(10))


def seed_default_expense_categories(apps, schema_editor):
    """
    Add only missing standard category codes to every historical Business.

    Existing rows, including a custom row with a reserved code, are retained as-is
    to prevent a data migration from silently replacing user-owned data.
    """
    Business = apps.get_model("businesses", "Business")
    ExpenseCategory = apps.get_model("expenses", "ExpenseCategory")

    for business in Business.objects.iterator():
        for sort_order, (code, name) in enumerate(STANDARD_EXPENSE_CATEGORIES):
            if ExpenseCategory.objects.filter(business_id=business.pk, code=code).exists():
                continue
            while True:
                public_id = generate_public_id()
                if not ExpenseCategory.objects.filter(public_id=public_id).exists():
                    break
            ExpenseCategory.objects.create(
                public_id=public_id,
                business_id=business.pk,
                code=code,
                name=name,
                is_system=True,
                is_active=True,
                sort_order=sort_order,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0002_expense_expense_amount_positive"),
    ]

    operations = [
        migrations.RunPython(seed_default_expense_categories, migrations.RunPython.noop),
    ]
