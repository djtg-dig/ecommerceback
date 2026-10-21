"""Introduce explicit commercial types without reclassifying historic credit sales."""

from django.db import migrations, models
from django.db.models import Q


def preserve_historic_sales(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    # Historical partial payments cannot safely be interpreted as invoices.
    # They retain the legacy direct-sale classification and completed rows have
    # already produced their stock movements under the old service.
    Sale.objects.filter(status="COMPLETED").update(stock_deducted=True)


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]

    operations = [
        migrations.AddField(model_name="sale", name="customer_name_snapshot", field=models.CharField(blank=True, max_length=200)),
        migrations.AddField(model_name="sale", name="operation_type", field=models.CharField(choices=[("DIRECT_SALE", "Direct sale"), ("INVOICE", "Invoice")], default="DIRECT_SALE", max_length=16)),
        migrations.AddField(model_name="sale", name="invoice_number", field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name="sale", name="issued_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="sale", name="due_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="sale", name="stock_deducted", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="saleline", name="item_name_snapshot", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="saleline", name="sku_snapshot", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="saleline", name="unit_symbol_snapshot", field=models.CharField(blank=True, max_length=20)),
        migrations.AddConstraint(model_name="sale", constraint=models.UniqueConstraint(condition=~Q(("invoice_number", "")), fields=("business", "invoice_number"), name="sale_business_invoice_number_unique")),
        migrations.RunPython(preserve_historic_sales, migrations.RunPython.noop),
    ]
