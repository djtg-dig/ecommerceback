"""Seed a compact, platform-owned starter taxonomy."""

from django.db import migrations


def seed_demo_taxonomy(apps, schema_editor):
    """Create only absent records so administrators' changes are preserved."""
    ProductCategory = apps.get_model("catalog", "ProductCategory")
    roots = {
        "ELECTRONICS": ("Électronique", "electronics", 10),
        "FASHION": ("Mode", "fashion", 20),
        "FOOD": ("Alimentation", "food", 30),
    }
    for code, (name, slug, sort_order) in roots.items():
        ProductCategory.objects.get_or_create(
            code=code,
            defaults={"name": name, "slug": slug, "sort_order": sort_order},
        )

    categories = (
        ("PHONES", "Téléphones", "phones", "ELECTRONICS", None, 10),
        ("SMARTPHONES", "Smartphones", "smartphones", "PHONES", "SMARTPHONE", 10),
        ("SHOES", "Chaussures", "shoes", "FASHION", "SHOES", 10),
        ("DRINKS", "Boissons", "drinks", "FOOD", "DRINK", 10),
    )
    for code, name, slug, parent_code, product_type_key, sort_order in categories:
        ProductCategory.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "slug": slug,
                "parent": ProductCategory.objects.get(code=parent_code),
                "product_type_key": product_type_key,
                "sort_order": sort_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]

    operations = [migrations.RunPython(seed_demo_taxonomy, migrations.RunPython.noop)]
