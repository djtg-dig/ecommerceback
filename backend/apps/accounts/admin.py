from django.contrib import admin

from .models import CarriIdentity


@admin.register(CarriIdentity)
class CarriIdentityAdmin(admin.ModelAdmin):
    list_display = ("id", "carri_subject", "linked_at", "last_login_at")
    search_fields = ("carri_subject",)
    readonly_fields = ("id", "carri_subject", "linked_at", "last_login_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
