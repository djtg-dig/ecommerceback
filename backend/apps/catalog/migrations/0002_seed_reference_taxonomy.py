from django.db import migrations


def seed_reference_taxonomy(apps, schema_editor):
    Category = apps.get_model("catalog", "ProductCategory")
    roots = {
        "ELECTRONICS": ("Électronique", "electronics", 10),
        "FASHION": ("Mode", "fashion", 20),
        "FOOD": ("Alimentation", "food", 30),
    }
    for code, (name, slug, sort_order) in roots.items():
        Category.objects.get_or_create(code=code, defaults={"name": name, "slug": slug, "sort_order": sort_order})
    for code, name, slug, parent_code, product_type_key, sort_order in (
        ("PHONES", "Téléphones", "phones", "ELECTRONICS", None, 10),
        ("SMARTPHONES", "Smartphones", "smartphones", "PHONES", "SMARTPHONE", 10),
        ("SHOES", "Chaussures", "shoes", "FASHION", "SHOES", 10),
        ("DRINKS", "Boissons", "drinks", "FOOD", "DRINK", 10),
    ):
        Category.objects.get_or_create(code=code, defaults={"name": name, "slug": slug, "parent": Category.objects.get(code=parent_code), "product_type_key": product_type_key, "sort_order": sort_order})


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(seed_reference_taxonomy, migrations.RunPython.noop)]
