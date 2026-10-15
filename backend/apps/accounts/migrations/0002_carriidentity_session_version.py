# Generated for local E-commerce session revocation.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="carriidentity",
            name="session_version",
            field=models.PositiveBigIntegerField(default=1),
        ),
    ]
