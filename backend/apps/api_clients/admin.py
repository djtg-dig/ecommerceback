from django.contrib import admin

from .models import ApiClient, ClientNonce


@admin.register(ApiClient)
class ApiClientAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "name",
        "client_id",
        "client_type",
        "auth_method",
        "is_active",
        "last_seen_at",
    )
    list_filter = ("client_type", "auth_method", "is_active")
    search_fields = ("reference", "name", "client_id")
    readonly_fields = ("reference", "last_seen_at", "created_at", "updated_at")
    fieldsets = (
        (
            "Identite",
            {
                "fields": (
                    "reference",
                    "name",
                    "client_id",
                    "client_type",
                    "auth_method",
                    "description",
                )
            },
        ),
        (
            "Acces et suivi",
            {
                "fields": (
                    "is_active",
                    "metadata",
                    "last_seen_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(ClientNonce)
class ClientNonceAdmin(admin.ModelAdmin):
    list_display = ("client", "nonce", "seen_at")
    list_filter = ("client",)
    search_fields = ("nonce", "client__client_id")
    readonly_fields = ("client", "nonce", "seen_at")
    date_hierarchy = "seen_at"
