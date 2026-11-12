from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_carriidentity_preferred_language")]

    operations = [
        migrations.AddField(
            model_name="carriidentity",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="carriidentity",
            name="last_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
    ]
