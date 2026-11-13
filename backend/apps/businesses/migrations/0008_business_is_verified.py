from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("businesses", "0007_alter_businessmemberpermission_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="is_verified",
            field=models.BooleanField(
                default=False,
                help_text="Indique si l'entreprise a été vérifiée par Carri Business.",
                verbose_name="Entreprise vérifiée",
            ),
        ),
    ]
