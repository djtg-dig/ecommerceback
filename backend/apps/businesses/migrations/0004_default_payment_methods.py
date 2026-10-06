from django.db import migrations


def create_default_payment_methods(apps, schema_editor):
    Business = apps.get_model("businesses", "Business")
    BusinessPaymentMethod = apps.get_model("businesses", "BusinessPaymentMethod")
    defaults = (
        ("Argent liquide", "CASH"),
        ("Mobile Money", "MOBILE_MONEY"),
        ("Virement bancaire", "BANK_TRANSFER"),
        ("Carte", "CARD"),
        ("Autre", "OTHER"),
    )
    for business in Business.objects.iterator():
        for name, category in defaults:
            BusinessPaymentMethod.objects.get_or_create(
                business_id=business.pk,
                name=name,
                defaults={"category": category, "public_id": "PM" + (str(business.pk).replace("-", "")[:7] + category[:3]).upper()},
            )


def reverse_default_payment_methods(apps, schema_editor):
    # Historical configured methods must remain available once created.
    pass


class Migration(migrations.Migration):
    dependencies = [("businesses", "0003_businesspaymentmethod")]
    operations = [migrations.RunPython(create_default_payment_methods, reverse_default_payment_methods)]
