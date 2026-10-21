from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("receivables", "0001_initial"), ("sales", "0002_invoice_sales")]

    operations = [
        migrations.AlterField(model_name="receivable", name="customer", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="sales.customer")),
        migrations.AddField(model_name="receivable", name="customer_name_snapshot", field=models.CharField(blank=True, max_length=200)),
    ]
