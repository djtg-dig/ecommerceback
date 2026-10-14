import secrets

from django.db import migrations


STANDARD = (("RENT", "Loyer"), ("ELECTRICITY", "Électricité"), ("WATER", "Eau"), ("INTERNET", "Internet"), ("TRANSPORT", "Transport"), ("SALARY", "Salaire"), ("MAINTENANCE", "Maintenance"), ("SUPPLIES", "Fournitures"), ("TAX", "Taxe / impôt"), ("MARKETING", "Marketing"), ("OTHER", "Autre"))
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def seed_categories(apps, schema_editor):
    Business = apps.get_model("businesses", "Business")
    Category = apps.get_model("expenses", "ExpenseCategory")
    for business in Business.objects.iterator():
        for order, (code, name) in enumerate(STANDARD):
            if Category.objects.filter(business_id=business.pk, code=code).exists():
                continue
            while True:
                public_id = "EC" + "".join(secrets.choice(ALPHABET) for _ in range(10))
                if not Category.objects.filter(public_id=public_id).exists():
                    break
            Category.objects.create(public_id=public_id, business_id=business.pk, code=code, name=name, is_system=True, is_active=True, sort_order=order)


class Migration(migrations.Migration):
    dependencies = [("businesses", "0001_initial"), ("expenses", "0001_initial")]
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
