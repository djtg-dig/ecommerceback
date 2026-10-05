from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Ecommerce identities"

    def ready(self):
        """Register OpenAPI extensions after Django has loaded the app registry."""
        from . import openapi  # noqa: F401
