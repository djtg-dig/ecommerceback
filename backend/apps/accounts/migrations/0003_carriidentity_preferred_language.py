# Generated for persistent E-commerce interface language preferences.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_carriidentity_session_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="carriidentity",
            name="preferred_language",
            field=models.CharField(
                blank=True,
                choices=[("fr", "Français"), ("en", "English")],
                default="",
                max_length=2,
            ),
        ),
    ]
