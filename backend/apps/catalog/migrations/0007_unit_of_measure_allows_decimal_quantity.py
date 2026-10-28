from django.db import migrations, models


DECIMAL_CATEGORIES = ("MASS", "VOLUME", "LENGTH", "AREA")


def mark_divisible_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model("catalog", "UnitOfMeasure")
    UnitOfMeasure.objects.filter(category__in=DECIMAL_CATEGORIES).update(
        allows_decimal_quantity=True
    )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0006_unit_of_measure")]

    operations = [
        migrations.AddField(
            model_name="unitofmeasure",
            name="allows_decimal_quantity",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_divisible_units, migrations.RunPython.noop),
    ]
