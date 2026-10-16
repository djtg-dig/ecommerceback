from django.db import migrations, models
import django.db.models.deletion


def validate_existing_category_sources(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    invalid = Product.objects.filter(category_id__isnull=True).count()
    if invalid:
        raise RuntimeError(
            f"{invalid} produit(s) historique(s) n'ont aucune catégorie; "
            "la migration progressive ne peut pas continuer."
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_seed_reference_taxonomy")]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="products",
                to="catalog.productcategory",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="category_code",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.RunPython(validate_existing_category_sources, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("category__isnull", False), ("category_code__isnull", True))
                    | (
                        models.Q(("category__isnull", True), ("category_code__isnull", False))
                        & ~models.Q(("category_code", ""))
                    )
                ),
                name="catalog_product_exactly_one_category_source",
            ),
        ),
    ]
