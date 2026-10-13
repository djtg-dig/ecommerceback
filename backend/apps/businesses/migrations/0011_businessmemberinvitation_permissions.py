from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("businesses", "0010_businessmemberinvitation_declined_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessmemberinvitation",
            name="permissions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
