from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_carriidentity_names")]

    operations = [
        migrations.AddField(
            model_name="carriidentity",
            name="avatar_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
    ]
