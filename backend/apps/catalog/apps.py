from django.apps import AppConfig


class CatalogConfig(AppConfig):
    """Register the global, business-independent product catalog app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
