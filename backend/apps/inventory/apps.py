from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """Register inventory independently from catalog descriptions."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
