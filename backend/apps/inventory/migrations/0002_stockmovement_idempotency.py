from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="idempotency_fingerprint",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="idempotency_key",
            field=models.CharField(blank=True, editable=False, max_length=255),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.UniqueConstraint(
                condition=~Q(idempotency_key=""),
                fields=("business", "idempotency_key"),
                name="stock_movement_business_idempotency_key",
            ),
        ),
    ]
