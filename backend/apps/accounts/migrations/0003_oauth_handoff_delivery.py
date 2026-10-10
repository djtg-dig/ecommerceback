# Generated manually to preserve the existing OAuth handoff data.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_carriidentity_email_verified_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthloginattempt",
            name="browser_binding_hash",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="oauthloginattempt",
            name="handoff_delivery_binding_hash",
            field=models.CharField(blank=True, default="", editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="oauthloginattempt",
            name="handoff_delivery_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="oauthhandoff",
            name="consumer_client_id",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
