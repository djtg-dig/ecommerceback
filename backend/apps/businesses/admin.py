from django.contrib import admin

from .models import Business, BusinessMember


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "primary_currency",
        "created_at",
    )


@admin.register(BusinessMember)
class BusinessMemberAdmin(admin.ModelAdmin):
    list_display = (
        "business",
        "identity",
        "role",
        "status",
        "joined_at",
    )
    readonly_fields = (
        "identity",
        "business",
        "role",
        "status",
        "joined_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
