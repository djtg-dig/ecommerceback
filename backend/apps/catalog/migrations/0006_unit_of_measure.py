import uuid

import django.db.models.deletion
from django.db import migrations, models


UNITS = (
    ("PCS", "Pièce", "pce", "COUNT"), ("PAIR", "Paire", "paire", "COUNT"),
    ("DOZEN", "Douzaine", "dz", "COUNT"), ("LOT", "Lot", "lot", "COUNT"),
    ("MG", "Milligramme", "mg", "MASS"), ("G", "Gramme", "g", "MASS"),
    ("KG", "Kilogramme", "kg", "MASS"), ("T", "Tonne", "t", "MASS"),
    ("ML", "Millilitre", "mL", "VOLUME"), ("L", "Litre", "L", "VOLUME"),
    ("M3", "Mètre cube", "m³", "VOLUME"), ("CM", "Centimètre", "cm", "LENGTH"),
    ("M", "Mètre", "m", "LENGTH"), ("KM", "Kilomètre", "km", "LENGTH"),
    ("M2", "Mètre carré", "m²", "AREA"), ("BAG", "Sac", "sac", "PACKAGING"),
    ("BOX", "Boîte", "boîte", "PACKAGING"), ("CARTON", "Carton", "carton", "PACKAGING"),
    ("PACK", "Paquet", "paquet", "PACKAGING"), ("SACHET", "Sachet", "sachet", "PACKAGING"),
    ("BOTTLE", "Bouteille", "bouteille", "PACKAGING"), ("CAN", "Bidon", "bidon", "PACKAGING"),
    ("ROLL", "Rouleau", "rouleau", "PACKAGING"), ("PALLET", "Palette", "palette", "PACKAGING"),
)


def seed_units_and_products(apps, schema_editor):
    UnitOfMeasure = apps.get_model("catalog", "UnitOfMeasure")
    Product = apps.get_model("catalog", "Product")
    for code, name, symbol, category in UNITS:
        UnitOfMeasure.objects.update_or_create(code=code, defaults={"name": name, "symbol": symbol, "category": category})
    Product.objects.filter(unit_of_measure__isnull=True).update(unit_of_measure=UnitOfMeasure.objects.get(code="PCS"))


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_media_management")]

    operations = [
        migrations.CreateModel(
            name="UnitOfMeasure",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=30, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("symbol", models.CharField(max_length=20)),
                ("category", models.CharField(max_length=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("category", "code")},
        ),
        migrations.AddField(
            model_name="product", name="unit_of_measure",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="products", to="catalog.unitofmeasure"),
        ),
        migrations.RunPython(seed_units_and_products, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="product", name="unit_of_measure",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="catalog.unitofmeasure"),
        ),
    ]
